from tests.conftest import csrf
from routers.hr_book import bank_code


def _emp(db, book, name, bank_name="", bank_account="", employee_no="E1"):
    return db.execute(
        "INSERT INTO employees (name, company_id, employee_no, status, bank_name, bank_account) "
        "VALUES (?,?,?,'active',?,?)",
        (name, book, employee_no, bank_name, bank_account),
    ).lastrowid


def _payslip(db, emp_id, year, month, net_pay, status="confirmed"):
    return db.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, total_deduction, net_pay,
               pay_date, status) VALUES (?,?,?,?,0,?,?,?)""",
        (emp_id, year, month, net_pay, net_pay, f"{year}-{month:02d}-25", status),
    ).lastrowid


def _bank_account(db, book, account_no="110-123-456789"):
    return db.execute(
        "INSERT INTO bank_accounts (company_id, bank, account_no, name) VALUES (?,'국민',?,'급여통장')",
        (book, account_no),
    ).lastrowid


def test_bank_code_matching():

    assert bank_code("KB국민은행") == "004"
    assert bank_code("국민") == "004"
    assert bank_code("NH농협") == "011"
    assert bank_code("카카오뱅크") == "090"
    assert bank_code("토스") == "092"
    assert bank_code("듣보은행") == ""
    assert bank_code("") == ""


def test_transfer_page_excludes_missing_account_and_flags_code(db, seed, login):
    a = seed["a"]["company"]
    e1 = _emp(db, a, "정상", "국민은행", "123456-01-123456", "E1")
    e2 = _emp(db, a, "계좌없음", "", "", "E2")
    e3 = _emp(db, a, "모르는은행", "듣보은행", "111-222-333", "E3")
    _payslip(db, e1, 2026, 3, 2_700_000)
    _payslip(db, e2, 2026, 3, 2_700_000)
    _payslip(db, e3, 2026, 3, 2_700_000)
    db.commit()

    c = login("a_mgr")
    html = c.get("/payroll/transfer?year=2026&month=3").text
    assert "정상" in html
    assert "계좌없음" in html
    assert "모르는은행" in html
    assert "계좌 없음" in html
    assert "코드 확인" in html
    assert "대상" in html
    assert "3" in html


def test_draft_payslip_and_other_book_excluded(db, seed, login):
    a = seed["a"]["company"]
    b = seed["b"]["company"]
    e1 = _emp(db, a, "확정자", "국민은행", "123-456", "E1")
    e2 = _emp(db, a, "미확정자", "국민은행", "123-457", "E2")
    e3 = _emp(db, b, "타장부", "국민은행", "999-999", "E3")
    _payslip(db, e1, 2026, 3, 2_700_000, status="confirmed")
    _payslip(db, e2, 2026, 3, 2_700_000, status="draft")
    _payslip(db, e3, 2026, 3, 2_700_000, status="confirmed")
    db.commit()

    c = login("a_mgr")
    html = c.get("/payroll/transfer?year=2026&month=3").text
    assert "확정자" in html
    assert "미확정자" not in html
    assert "타장부" not in html


def test_csv_headers_amounts_and_withdrawal_label(db, seed, login):
    a = seed["a"]["company"]
    e1 = _emp(db, a, "정상1", "국민은행", "123456-01-123456", "E1")
    e2 = _emp(db, a, "계좌없음", "", "", "E2")
    e3 = _emp(db, a, "모르는은행", "듣보은행", "111-222-333", "E3")
    _payslip(db, e1, 2026, 3, 2_700_000)
    _payslip(db, e2, 2026, 3, 2_700_000)
    _payslip(db, e3, 2026, 3, 2_700_000)
    acct_id = _bank_account(db, a)
    db.commit()

    c = login("a_mgr")
    r = c.get(f"/payroll/transfer/csv?year=2026&month=3&reason=test&account_id={acct_id}")
    assert r.status_code == 200
    body = r.content.decode("utf-8-sig")
    lines = [l for l in body.strip().split("\r\n") if l]
    assert lines[0] == "입금은행코드,입금계좌번호,입금액,예금주,입금통장표시,출금통장표시"

    rows = lines[1:]
    assert len(rows) == 2  # 계좌없음 제외
    normal = next(l for l in rows if "정상1" in l)
    cols = normal.split(",")
    assert cols[0] == "004"
    assert cols[1] == "12345601123456"
    assert cols[2] == "2700000"
    assert cols[3] == "정상1"
    assert cols[4] == "가테스트"
    assert cols[5] == "2026년 3월 급여"

    unknown = next(l for l in rows if "모르는은행" in l)
    assert unknown.split(",")[0] == ""

    assert not any("계좌없음" in l for l in rows)

    ps_id = db.execute(
        "SELECT id FROM payslips WHERE employee_id=?", (e1,)
    ).fetchone()["id"]
    assert db.execute("SELECT transfer_file_at FROM payslips WHERE id=?", (ps_id,)).fetchone()["transfer_file_at"]

    log = db.execute(
        "SELECT action, target_type, company_id, summary FROM audit_logs WHERE action='payroll_transfer'"
    ).fetchone()
    assert log["target_type"] == "payslip"
    assert log["company_id"] == a
    assert "2026년 3월" in log["summary"]
    assert "2명" in log["summary"]


def test_csv_other_book_account_404(db, seed, login):
    a = seed["a"]["company"]
    b = seed["b"]["company"]
    e1 = _emp(db, a, "정상", "국민은행", "123-456", "E1")
    _payslip(db, e1, 2026, 3, 2_700_000)
    other_acct = _bank_account(db, b)
    db.commit()

    c = login("a_mgr")
    r = c.get(f"/payroll/transfer/csv?year=2026&month=3&reason=test&account_id={other_acct}")
    assert r.status_code == 404


def test_csv_redownload_allowed(db, seed, login):
    a = seed["a"]["company"]
    e1 = _emp(db, a, "정상", "국민은행", "123-456", "E1")
    _payslip(db, e1, 2026, 3, 2_700_000)
    acct_id = _bank_account(db, a)
    db.commit()

    c = login("a_mgr")
    r1 = c.get(f"/payroll/transfer/csv?year=2026&month=3&reason=test&account_id={acct_id}")
    r2 = c.get(f"/payroll/transfer/csv?year=2026&month=3&reason=test&account_id={acct_id}")
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_bank_account_change_logged_and_notified(db, seed, login):
    emp = db.execute("SELECT id, user_id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()
    login("a_mgr").post(f"/payroll/{emp['id']}/info", data={"bank_name": "국민은행", "bank_account": "110-123-456789"})
    row = db.execute("SELECT * FROM audit_logs WHERE action='bank_account_change'").fetchone()
    assert row and "6789" in row["detail"] and "456789" not in row["detail"]
    assert db.execute("SELECT 1 FROM notifications WHERE user_id=? AND title='급여 계좌 변경'", (emp["user_id"],)).fetchone()

    login("a_wk").post("/mypage/profile/save", data={"bank_name": "신한은행", "bank_account": "222-333-444555"})
    assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='bank_account_change'").fetchone()[0] == 2
    assert db.execute("SELECT 1 FROM notifications WHERE user_id=? AND title='근로자 급여 계좌 변경'", (seed["a"]["mgr"],)).fetchone()
