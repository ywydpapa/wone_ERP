def test_worker_blocked_from_hr_employees(db, seed, login):
    c = login("a_wk")
    r = c.get("/hr/employees", follow_redirects=False)
    assert r.status_code == 303


def test_client_blocked_from_hr_employees(db, seed, login):
    c = login("a_mgr")
    r = c.get("/hr/employees", follow_redirects=False)
    assert r.status_code == 303


def test_old_hr_payroll_ledger_gone(db, seed, login):
    c = login("t_staff")
    r = c.get("/hr/payroll/ledger", follow_redirects=False)
    assert r.status_code == 404


def test_staff_allowed_hr_employees(db, seed, login):
    c = login("t_staff")
    r = c.get("/hr/employees")
    assert r.status_code == 200


def test_staff_allowed_payroll_ledger(db, seed, login):
    c = login("t_staff")
    r = c.get("/payroll/ledger")
    assert r.status_code == 200
