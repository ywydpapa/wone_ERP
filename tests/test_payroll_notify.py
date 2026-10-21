from tests.conftest import csrf


def _emp_with_user(db, book, name, username):
    uid = db.execute(
        "INSERT INTO users (username, password, name, role) VALUES (?,'x',?,'worker')",
        (username, name),
    ).lastrowid
    emp_id = db.execute(
        "INSERT INTO employees (name, company_id, status, monthly_work_hours, user_id) VALUES (?,?,'active',209,?)",
        (name, book, uid),
    ).lastrowid
    return emp_id, uid


def _draft_payslip(db, emp_id, year, month, gross=3_000_000, net=2_700_000):
    return db.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, income_tax, resident_tax,
               national_pension, health_insurance, long_care, employment_insurance,
               total_deduction, net_pay, pay_date, status)
           VALUES (?,?,?,?,100000,10000,100000,60000,8000,22000,?,?,?,'draft')""",
        (emp_id, year, month, gross, gross - net, net, f"{year}-{month:02d}-25"),
    ).lastrowid


def _close_attendance(db, book, year, month):
    db.execute(
        "INSERT INTO attendance_closings (year, month, company_id, status) VALUES (?,?,?,'closed')",
        (year, month, book),
    )


def test_payroll_confirm_notifies_worker(db, seed, login):
    a = seed["a"]["company"]
    emp_id, uid = _emp_with_user(db, a, "확정알림", "notify_wk")
    _draft_payslip(db, emp_id, 2026, 10)
    _close_attendance(db, a, 2026, 10)
    db.commit()

    c = login("a_mgr")
    tok = csrf(c, "/payroll")
    r = c.post(
        "/payroll/confirm",
        data={"csrf_token": tok, "year": "2026", "month": "10"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    notif = db.execute("SELECT * FROM notifications WHERE user_id=?", (uid,)).fetchone()
    assert notif and notif["link"] == "/payslip"
    assert "2026년 10월" in notif["title"]


def test_payroll_confirm_skips_notify_when_no_login_account(db, seed, login):
    a = seed["a"]["company"]
    emp_id = db.execute(
        "INSERT INTO employees (name, company_id, status, monthly_work_hours) VALUES (?,?,'active',209)",
        ("계정없음", a),
    ).lastrowid
    _draft_payslip(db, emp_id, 2026, 10)
    _close_attendance(db, a, 2026, 10)
    db.commit()

    c = login("a_mgr")
    tok = csrf(c, "/payroll")
    r = c.post(
        "/payroll/confirm",
        data={"csrf_token": tok, "year": "2026", "month": "10"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert db.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"] == 0
