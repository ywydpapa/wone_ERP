from tests.conftest import csrf
from core.payroll import below_min_wage


def _emp(db, book, name, employee_no="E1", monthly_hours=209):
    return db.execute(
        "INSERT INTO employees (name, company_id, employee_no, status, monthly_work_hours) "
        "VALUES (?,?,?,'active',?)",
        (name, book, employee_no, monthly_hours),
    ).lastrowid


def _draft_payslip(db, emp_id, year, month, gross=3_000_000, net=2_700_000):
    return db.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, income_tax, resident_tax,
               national_pension, health_insurance, long_care, employment_insurance,
               total_deduction, net_pay, pay_date, status)
           VALUES (?,?,?,?,100000,10000,100000,60000,8000,22000,?,?,?,'draft')""",
        (emp_id, year, month, gross, gross - net, net, f"{year}-{month:02d}-25"),
    ).lastrowid


def _close_attendance(db, book, year, month):
    exists = db.execute(
        "SELECT 1 FROM attendance_closings WHERE year=? AND month=? AND company_id=?",
        (year, month, book),
    ).fetchone()
    if not exists:
        db.execute(
            "INSERT INTO attendance_closings (year, month, company_id, status) VALUES (?,?,?,'closed')",
            (year, month, book),
        )


def _confirm(c, db, book, year, month):
    _close_attendance(db, book, year, month)
    db.commit()
    tok = csrf(c, "/payroll")
    return c.post(
        "/payroll/confirm",
        data={"csrf_token": tok, "year": str(year), "month": str(month)},
        follow_redirects=False,
    )


def test_confirm_credits_254_not_103(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동")
    _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    r = _confirm(c, db, a, 2026, 10)
    assert r.status_code == 303

    ps = db.execute("SELECT id FROM payslips WHERE employee_id=?", (emp,)).fetchone()
    doc = db.execute("SELECT id FROM erp_docs WHERE payslip_id=?", (ps["id"],)).fetchone()
    lines = db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (doc["id"],)
    ).fetchall()
    codes = {l["account_code"]: (l["debit"], l["credit"]) for l in lines}
    assert codes["254"] == (0, 2_700_000)
    assert "103" not in codes


def test_pay_creates_slip_and_marks_paid(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동")
    ps_id = _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    _confirm(c, db, a, 2026, 10)

    tok = csrf(c, "/payroll")
    r = c.post(
        "/payroll/pay",
        data={"csrf_token": tok, "year": "2026", "month": "10", "pay_date": "2026-10-25", "account_id": "0"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    ps = db.execute("SELECT paid_at, pay_doc_id FROM payslips WHERE id=?", (ps_id,)).fetchone()
    assert ps["paid_at"]
    assert ps["pay_doc_id"]

    lines = db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (ps["pay_doc_id"],)
    ).fetchall()
    codes = {l["account_code"]: (l["debit"], l["credit"]) for l in lines}
    assert codes["254"] == (2_700_000, 0)
    assert codes["103"] == (0, 2_700_000)

    before = db.execute("SELECT COUNT(*) FROM erp_docs WHERE source_type='payroll_pay'").fetchone()[0]
    r2 = c.post(
        "/payroll/pay",
        data={"csrf_token": tok, "year": "2026", "month": "10", "pay_date": "2026-10-25", "account_id": "0"},
        follow_redirects=False,
    )
    assert r2.status_code == 303
    after = db.execute("SELECT COUNT(*) FROM erp_docs WHERE source_type='payroll_pay'").fetchone()[0]
    assert after == before


def test_reopen_wrong_password_rejected(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동")
    _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    _confirm(c, db, a, 2026, 10)

    tok = csrf(c, f"/payroll/{emp}")
    r = c.post(
        f"/payroll/{emp}/reopen",
        data={"csrf_token": tok, "year": "2026", "month": "10", "reason": "오류", "password": "wrong"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    ps = db.execute("SELECT status FROM payslips WHERE employee_id=?", (emp,)).fetchone()
    assert ps["status"] == "confirmed"


def test_reopen_success_reverses_and_allows_reconfirm(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동")
    _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    _confirm(c, db, a, 2026, 10)

    ps_before = db.execute("SELECT id FROM payslips WHERE employee_id=?", (emp,)).fetchone()
    orig_doc = db.execute("SELECT id FROM erp_docs WHERE payslip_id=?", (ps_before["id"],)).fetchone()

    tok = csrf(c, f"/payroll/{emp}")
    r = c.post(
        f"/payroll/{emp}/reopen",
        data={"csrf_token": tok, "year": "2026", "month": "10", "reason": "사유", "password": "1234"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    ps = db.execute("SELECT status, paid_at FROM payslips WHERE id=?", (ps_before["id"],)).fetchone()
    assert ps["status"] == "draft"
    assert ps["paid_at"] is None

    rev = db.execute("SELECT id FROM erp_docs WHERE reversal_of=?", (orig_doc["id"],)).fetchone()
    assert rev

    bal = db.execute(
        "SELECT SUM(debit) - SUM(credit) FROM slip_lines WHERE doc_id IN (?,?) AND account_code='254'",
        (orig_doc["id"], rev["id"]),
    ).fetchone()[0]
    assert bal == 0

    r2 = _confirm(c, db, a, 2026, 10)
    assert r2.status_code == 303
    new_doc_cnt = db.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE payslip_id=? AND id != ?",
        (ps_before["id"], orig_doc["id"]),
    ).fetchone()[0]
    assert new_doc_cnt == 1

    # 재확정 후 두 번째 취소는 새 전표를 역분개
    tok = csrf(c, f"/payroll/{emp}")
    c.post(
        f"/payroll/{emp}/reopen",
        data={"csrf_token": tok, "year": "2026", "month": "10", "reason": "재취소", "password": "1234"},
        follow_redirects=False,
    )
    assert db.execute("SELECT status FROM payslips WHERE id=?", (ps_before["id"],)).fetchone()["status"] == "draft"
    open_docs = db.execute(
        """SELECT COUNT(*) FROM erp_docs d WHERE payslip_id=?
           AND NOT EXISTS (SELECT 1 FROM erp_docs r WHERE r.reversal_of=d.id)""",
        (ps_before["id"],),
    ).fetchone()[0]
    assert open_docs == 0


def test_reopen_rejected_after_payment(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동")
    _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    _confirm(c, db, a, 2026, 10)
    tok = csrf(c, "/payroll")
    c.post(
        "/payroll/pay",
        data={"csrf_token": tok, "year": "2026", "month": "10", "pay_date": "2026-10-25", "account_id": "0"},
    )

    tok2 = csrf(c, f"/payroll/{emp}")
    r = c.post(
        f"/payroll/{emp}/reopen",
        data={"csrf_token": tok2, "year": "2026", "month": "10", "reason": "사유", "password": "1234"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    ps = db.execute("SELECT status FROM payslips WHERE employee_id=?", (emp,)).fetchone()
    assert ps["status"] == "confirmed"


def test_reopen_rejected_when_transferred(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동")
    ps_id = _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    _confirm(c, db, a, 2026, 10)
    db.execute("UPDATE payslips SET transfer_file_at=? WHERE id=?", ("2026-10-24 10:00:00", ps_id))
    db.commit()

    tok = csrf(c, f"/payroll/{emp}")
    r = c.post(
        f"/payroll/{emp}/reopen",
        data={"csrf_token": tok, "year": "2026", "month": "10", "reason": "사유", "password": "1234"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    ps = db.execute("SELECT status FROM payslips WHERE employee_id=?", (emp,)).fetchone()
    assert ps["status"] == "confirmed"


def test_reopen_rejected_when_fi_closing_closed(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동")
    _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    _confirm(c, db, a, 2026, 10)

    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,10,'closed')", (a,))
    db.commit()

    tok = csrf(c, f"/payroll/{emp}")
    r = c.post(
        f"/payroll/{emp}/reopen",
        data={"csrf_token": tok, "year": "2026", "month": "10", "reason": "사유", "password": "1234"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    ps = db.execute("SELECT status FROM payslips WHERE employee_id=?", (emp,)).fetchone()
    assert ps["status"] == "confirmed"


def test_reopen_other_book_404(db, seed, login):
    a = seed["a"]["company"]
    b = seed["b"]["company"]
    emp_b = _emp(db, b, "타사직원")
    db.commit()

    c = login("a_mgr")
    tok = csrf(c, "/payroll")
    r = c.post(
        f"/payroll/{emp_b}/reopen",
        data={"csrf_token": tok, "year": "2026", "month": "10", "reason": "사유", "password": "1234"},
    )
    assert r.status_code == 404


def test_payroll_pages_render(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동", monthly_hours=0)
    _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    r1 = c.get(f"/payroll/{emp}?year=2026&month=10")
    assert r1.status_code == 200

    _confirm(c, db, a, 2026, 10)
    r2 = c.get(f"/payroll/{emp}?year=2026&month=10")
    assert r2.status_code == 200
    assert "확정 취소" in r2.text

    r3 = c.get("/payroll?year=2026&month=10")
    assert r3.status_code == 200
    assert "지급 처리" in r3.text

    c.post(
        "/payroll/pay",
        data={"csrf_token": csrf(c, "/payroll"), "year": "2026", "month": "10",
              "pay_date": "2026-10-25", "account_id": "0"},
    )
    r4 = c.get(f"/payroll/{emp}?year=2026&month=10")
    assert r4.status_code == 200
    assert "지급완료" in r4.text


def test_below_min_wage_judgement():
    assert below_min_wage(2_000_000, 209, 2026) is True
    assert below_min_wage(2_200_000, 209, 2026) is False
    assert below_min_wage(2_000_000, 0, 2026) is None


def _pay(c, db, year, month, ps_id, pay_date="2026-10-25"):
    tok = csrf(c, "/payroll")
    c.post(
        "/payroll/pay",
        data={"csrf_token": tok, "year": str(year), "month": str(month), "pay_date": pay_date, "account_id": "0"},
    )
    return db.execute("SELECT pay_doc_id FROM payslips WHERE id=?", (ps_id,)).fetchone()["pay_doc_id"]


def test_pay_cancel_clears_flags_and_allows_repay(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동")
    ps_id = _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    _confirm(c, db, a, 2026, 10)
    doc_id = _pay(c, db, 2026, 10, ps_id)
    assert doc_id

    tok = csrf(c, "/payroll")
    r = c.post(
        f"/payroll/pay/{doc_id}/cancel",
        data={"csrf_token": tok, "year": "2026", "month": "10", "reason": "오류", "password": "1234"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    ps = db.execute("SELECT paid_at, pay_doc_id, status FROM payslips WHERE id=?", (ps_id,)).fetchone()
    assert ps["paid_at"] is None
    assert ps["pay_doc_id"] is None
    assert ps["status"] == "confirmed"

    rev = db.execute("SELECT id FROM erp_docs WHERE reversal_of=?", (doc_id,)).fetchone()
    assert rev

    doc_id2 = _pay(c, db, 2026, 10, ps_id, pay_date="2026-10-26")
    assert doc_id2 and doc_id2 != doc_id
    ps2 = db.execute("SELECT paid_at FROM payslips WHERE id=?", (ps_id,)).fetchone()
    assert ps2["paid_at"]


def test_pay_cancel_wrong_password_rejected(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동")
    ps_id = _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    _confirm(c, db, a, 2026, 10)
    doc_id = _pay(c, db, 2026, 10, ps_id)

    tok = csrf(c, "/payroll")
    r = c.post(
        f"/payroll/pay/{doc_id}/cancel",
        data={"csrf_token": tok, "year": "2026", "month": "10", "reason": "오류", "password": "wrong"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=wrong_password" in r.headers["location"]
    ps = db.execute("SELECT paid_at FROM payslips WHERE id=?", (ps_id,)).fetchone()
    assert ps["paid_at"]


def test_pay_cancel_blocked_when_fi_closing_closed(db, seed, login):
    a = seed["a"]["company"]
    emp = _emp(db, a, "홍길동")
    ps_id = _draft_payslip(db, emp, 2026, 10)
    db.commit()

    c = login("a_mgr")
    _confirm(c, db, a, 2026, 10)
    doc_id = _pay(c, db, 2026, 10, ps_id)

    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,10,'closed')", (a,))
    db.commit()

    tok = csrf(c, "/payroll")
    r = c.post(
        f"/payroll/pay/{doc_id}/cancel",
        data={"csrf_token": tok, "year": "2026", "month": "10", "reason": "사유", "password": "1234"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=period_closed" in r.headers["location"]
    ps = db.execute("SELECT paid_at FROM payslips WHERE id=?", (ps_id,)).fetchone()
    assert ps["paid_at"]


def test_pay_cancel_other_book_404(db, seed, login):
    b = seed["b"]["company"]
    emp_b = _emp(db, b, "타사직원")
    ps_id = _draft_payslip(db, emp_b, 2026, 10)
    db.commit()

    cb = login("b_mgr")
    _confirm(cb, db, b, 2026, 10)
    doc_id = _pay(cb, db, 2026, 10, ps_id)

    c = login("a_mgr")
    tok = csrf(c, "/payroll")
    r = c.post(
        f"/payroll/pay/{doc_id}/cancel",
        data={"csrf_token": tok, "year": "2026", "month": "10", "reason": "사유", "password": "1234"},
    )
    assert r.status_code == 404
