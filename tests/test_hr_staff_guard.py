import pytest


@pytest.mark.parametrize(
    "role,path,expected",
    [
        ("a_wk", "/hr/employees", 303),
        ("a_mgr", "/hr/employees", 303),
        ("t_staff", "/hr/employees", 200),
        ("t_staff", "/payroll/ledger", 200),
    ],
)
def test_hr_staff_guard_by_role(db, seed, login, role, path, expected):
    c = login(role)
    r = c.get(path, follow_redirects=False)
    assert r.status_code == expected


def test_old_hr_payroll_ledger_gone(db, seed, login):
    c = login("t_staff")
    r = c.get("/hr/payroll/ledger", follow_redirects=False)
    assert r.status_code == 404


def test_staff_blocked_from_undelegated_worker(db, seed, login):
    emp_id = db.execute(
        "INSERT INTO employees (name, company_id, status) VALUES ('위탁외', ?, 'active')", (seed["a"]["company"],)
    ).lastrowid
    db.commit()
    c = login("t_staff")
    assert "위탁외" not in c.get("/hr/employees").text
    assert c.get(f"/hr/employees/{emp_id}").status_code == 404
    assert c.get(f"/hr/employees/{emp_id}/edit").status_code == 404

    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (seed["a"]["company"],))
    db.commit()
    assert c.get(f"/hr/employees/{emp_id}").status_code == 200


def test_staff_cannot_assign_undelegated_company(db, seed, login):
    c = login("t_staff")
    r = c.post("/hr/employees", data={"name": "배정시도", "company_id": str(seed["a"]["company"])})
    assert r.status_code == 400
