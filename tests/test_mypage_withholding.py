import hashlib

from core.pay_items import ensure_default_items


def _item_id(db, company_id, code):
    return db.execute(
        "SELECT id FROM pay_items WHERE company_id=? AND code=?", (company_id, code)
    ).fetchone()[0]


def _make_payslip(db, company_id, emp_id, pay_year, pay_month, items, status="confirmed", pay_date=None):
    ensure_default_items(db, company_id)
    gross = sum(items.values())
    income_tax, resident_tax = 1000, 100
    cur = db.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, income_tax, resident_tax,
               national_pension, health_insurance, employment_insurance, total_deduction, net_pay,
               pay_date, status)
           VALUES (?,?,?,?,?,?,0,0,0,?,?,?,?)""",
        (emp_id, pay_year, pay_month, gross, income_tax, resident_tax,
         income_tax + resident_tax, gross - income_tax - resident_tax, pay_date, status),
    )
    ps_id = cur.lastrowid
    for code, amt in items.items():
        db.execute(
            "INSERT INTO payslip_items (payslip_id, item_id, amount) VALUES (?,?,?)",
            (ps_id, _item_id(db, company_id, code), amt),
        )
    db.commit()
    return ps_id


def _verify(db, c, user_id, birth_date="1990-05-05", next="/mypage/withholding"):
    db.execute("UPDATE employees SET birth_date=? WHERE user_id=?", (birth_date, user_id))
    db.commit()
    return c.post(
        "/mypage/payslip/verify",
        data={"birth_date": birth_date, "next": next},
        follow_redirects=False,
    )


def test_worker_sees_own_record_with_masked_rno(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    db.execute("UPDATE employees SET resident_no=? WHERE id=?", ("990101-1234567", emp1))
    db.commit()
    _make_payslip(db, a, emp1, 2026, 9, {"BASE": 3000000}, pay_date="2026-09-25")

    c = login("a_wk")
    _verify(db, c, seed["a"]["wk"])
    r = c.get("/mypage/withholding?year=2026")
    assert r.status_code == 200
    assert "3,000,000" in r.text
    assert "990101-*******" in r.text
    assert "990101-1234567" not in r.text


def test_worker_cannot_see_other_employee_amounts(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    emp2 = db.execute(
        "INSERT INTO employees (name, company_id, employee_no) VALUES (?,?,?)",
        ("박근로", a, "E2"),
    ).lastrowid
    db.commit()
    _make_payslip(db, a, emp1, 2026, 9, {"BASE": 3000000}, pay_date="2026-09-25")
    _make_payslip(db, a, emp2, 2026, 9, {"BASE": 9990000}, pay_date="2026-09-25")

    c = login("a_wk")
    _verify(db, c, seed["a"]["wk"])
    r = c.get("/mypage/withholding?year=2026")
    assert r.status_code == 200
    assert "3,000,000" in r.text
    assert "9,990,000" not in r.text


def test_user_without_employee_row_redirected(db, seed, login):
    c = login("a_mgr")
    r = c.get("/mypage/withholding?year=2026", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/mypage"


def test_null_company_employee_uses_company_info(db, seed, login):
    pw = hashlib.sha256(b"1234").hexdigest()
    uid = db.execute(
        "INSERT INTO users (username, password, name, role) VALUES (?,?,?,?)",
        ("staff_wk", pw, "원플러스직원", "worker"),
    ).lastrowid
    emp = db.execute(
        "INSERT INTO employees (user_id, name, company_id) VALUES (?,?,NULL)",
        (uid, "원플러스직원"),
    ).lastrowid
    db.commit()

    c = login("staff_wk")
    _verify(db, c, uid)
    r = c.get("/mypage/withholding?year=2026")
    assert r.status_code == 200
    assert "(주)원플러스" in r.text


def test_draft_payslip_excluded(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 10, {"BASE": 4500000}, status="draft", pay_date="2026-10-25")

    c = login("a_wk")
    _verify(db, c, seed["a"]["wk"])
    r = c.get("/mypage/withholding?year=2026")
    assert r.status_code == 200
    assert "4,500,000" not in r.text


def test_unverified_withholding_shows_verify_page_without_amounts(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 9, {"BASE": 3000000}, pay_date="2026-09-25")

    c = login("a_wk")
    r = c.get("/mypage/withholding?year=2026")
    assert r.status_code == 200
    assert "본인 확인" in r.text
    assert "3,000,000" not in r.text


def test_wrong_birth_date_redirects_to_withholding_with_error(db, seed, login):
    db.execute("UPDATE employees SET birth_date=? WHERE user_id=?", ("1990-05-05", seed["a"]["wk"]))
    db.commit()

    c = login("a_wk")
    r = c.post(
        "/mypage/payslip/verify",
        data={"birth_date": "2000-01-01", "next": "/mypage/withholding"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/mypage/withholding?error=1"


def test_correct_birth_date_redirects_and_unlocks_record(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 9, {"BASE": 3000000}, pay_date="2026-09-25")

    c = login("a_wk")
    r = _verify(db, c, seed["a"]["wk"])
    assert r.status_code == 303
    assert r.headers["location"] == "/mypage/withholding"

    r2 = c.get("/mypage/withholding?year=2026")
    assert r2.status_code == 200
    assert "3,000,000" in r2.text


def test_verify_via_payslip_also_unlocks_withholding(db, seed, login):
    a = seed["a"]["company"]
    emp1 = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    _make_payslip(db, a, emp1, 2026, 9, {"BASE": 3000000}, pay_date="2026-09-25")

    c = login("a_wk")
    r = _verify(db, c, seed["a"]["wk"], next="/mypage/payslip")
    assert r.status_code == 303
    assert r.headers["location"] == "/mypage/payslip"

    r2 = c.get("/mypage/withholding?year=2026")
    assert r2.status_code == 200
    assert "3,000,000" in r2.text


def test_bad_next_falls_back_to_payslip(db, seed, login):
    c = login("a_wk")
    for bad in ("//evil.com", "/hr/employees"):
        r = _verify(db, c, seed["a"]["wk"], next=bad)
        assert r.status_code == 303
        assert r.headers["location"] == "/mypage/payslip"
