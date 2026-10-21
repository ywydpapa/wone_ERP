from core.crypto import dec_rno


def _employee_id(db, user_id):
    return db.execute("SELECT id FROM employees WHERE user_id=?", (user_id,)).fetchone()["id"]


def _set_client_role(db, user_id, role):
    db.execute("UPDATE client_users SET client_role=? WHERE user_id=?", (role, user_id))
    db.commit()


def test_worker_new_form_not_shadowed_by_detail_route(seed, login):
    c = login("a_mgr")
    r = c.get("/client/workers/new")
    assert r.status_code == 200


def test_cross_company_worker_edit_blocked(db, seed, login):
    b_emp_id = _employee_id(db, seed["b"]["wk"])
    c = login("a_mgr")
    r = c.get(f"/client/workers/{b_emp_id}/edit")
    assert r.status_code == 404
    r2 = c.post(f"/client/workers/{b_emp_id}/edit", data={
        "name": "해킹", "dept": "개발팀", "position": "사원", "status": "active",
    })
    assert r2.status_code == 404


def test_company_id_injection_ignored(db, seed, login):
    a_cid = seed["a"]["company"]
    b_cid = seed["b"]["company"]
    c = login("a_mgr")
    r = c.post("/client/workers", data={
        "name": "신규직원", "dept": "개발팀", "position": "사원", "status": "active",
        "company_id": str(b_cid),
    }, follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT company_id FROM employees WHERE name='신규직원'").fetchone()
    assert row["company_id"] == a_cid


def test_non_hr_client_cannot_edit_worker(db, seed, login):
    # 발급 가능한 값은 hr/all뿐이므로 그 외 값 강제 시 경계 확인
    _set_client_role(db, seed["a"]["mgr"], "limited")
    emp_id = _employee_id(db, seed["a"]["wk"])
    before = db.execute("SELECT resident_no, dept FROM employees WHERE id=?", (emp_id,)).fetchone()

    c = login("a_mgr")
    c.post(f"/client/workers/{emp_id}/edit", data={
        "name": "근로자", "dept": "개발팀", "position": "사원", "status": "active",
        "resident_no": "900101-1111111", "disability_type": "지체장애",
    }, follow_redirects=False)

    after = db.execute("SELECT resident_no, dept FROM employees WHERE id=?", (emp_id,)).fetchone()
    assert dict(after) == dict(before)


def test_hr_client_can_edit_pii(db, seed, login):
    _set_client_role(db, seed["a"]["mgr"], "hr")
    emp_id = _employee_id(db, seed["a"]["wk"])
    c = login("a_mgr")
    r = c.post(f"/client/workers/{emp_id}/edit", data={
        "name": "근로자", "dept": "개발팀", "position": "사원", "status": "active",
        "resident_no": "900101-1111111", "disability_type": "지체장애",
    }, follow_redirects=False)
    assert r.status_code == 303
    after = db.execute("SELECT resident_no, disability_type FROM employees WHERE id=?", (emp_id,)).fetchone()
    assert dec_rno(after["resident_no"]) == "900101-1111111"
    assert after["disability_type"] == "지체장애"


def test_cross_company_file_download_blocked(db, seed, login):
    a_emp = _employee_id(db, seed["a"]["wk"])
    c = login("a_mgr")
    up = c.post(f"/client/workers/{a_emp}/files", data={"kind": "계약서"},
                files={"file": ("contract.pdf", b"%PDF-1.4 fake")}, follow_redirects=False)
    assert up.status_code == 303
    path = db.execute("SELECT path FROM employee_files WHERE employee_id=?", (a_emp,)).fetchone()["path"]

    other = login("b_mgr")
    blocked = other.get(f"/files/employee/{path}")
    assert blocked.status_code == 404


def test_self_file_download_allowed(db, seed, login):
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (seed["a"]["company"],))
    db.commit()
    a_emp = _employee_id(db, seed["a"]["wk"])
    staff = login("t_staff")
    staff.post(f"/hr/employees/{a_emp}/files", data={"kind": "신분증"},
               files={"file": ("id.pdf", b"%PDF-1.4 fake")})
    path = db.execute("SELECT path FROM employee_files WHERE employee_id=?", (a_emp,)).fetchone()["path"]

    worker = login("a_wk")
    r = worker.get(f"/files/employee/{path}")
    assert r.status_code == 200


def test_dept_change_logs_appointment(db, seed, login):
    emp_id = _employee_id(db, seed["a"]["wk"])
    c = login("a_mgr")
    r = c.post(f"/client/workers/{emp_id}/edit", data={
        "name": "근로자", "dept": "생산팀", "position": "주임", "status": "active",
    }, follow_redirects=False)
    assert r.status_code == 303

    kinds = {row["kind"] for row in db.execute(
        "SELECT kind FROM hr_appointments WHERE employee_id=?", (emp_id,)
    ).fetchall()}
    assert "부서이동" in kinds
    assert "승진" in kinds


def test_base_salary_change_logs_appointment(db, seed, login):
    emp_id = _employee_id(db, seed["a"]["wk"])
    cid = seed["a"]["company"]
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (cid,))
    db.commit()

    c = login("a_mgr")
    r = c.post(f"/payroll/{emp_id}/info", data={
        "base_salary": "2500000", "monthly_work_hours": "173", "employment_insurance": "1",
        "tax_dependent_count": "1", "tax_child_count": "0", "tax_rate": "100",
        "bank_name": "", "bank_account": "",
    }, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute(
        "SELECT from_val, to_val FROM hr_appointments WHERE employee_id=? AND kind='급여변경'", (emp_id,)
    ).fetchone()
    assert row is not None
    assert row["to_val"] == "2500000"


def test_disguised_file_rejected(db, seed, login):
    a_emp = _employee_id(db, seed["a"]["wk"])
    c = login("a_mgr")
    r = c.post(f"/client/workers/{a_emp}/files", data={"kind": "신분증"},
               files={"file": ("id.pdf", b"<html><script>x</script>")}, follow_redirects=False)
    assert "file_err=1" in r.headers["location"]
    r = c.post(f"/client/workers/{a_emp}/files", data={"kind": "기타"},
               files={"file": ("a.zip", b"PK\x03\x04")}, follow_redirects=False)
    assert "file_err=1" in r.headers["location"]
    assert db.execute("SELECT COUNT(*) FROM employee_files WHERE employee_id=?", (a_emp,)).fetchone()[0] == 0


def test_file_view_audited(db, seed, login):
    a_emp = _employee_id(db, seed["a"]["wk"])
    c = login("a_mgr")
    c.post(f"/client/workers/{a_emp}/files", data={"kind": "통장"},
           files={"file": ("bank.png", b"\x89PNG\r\n\x1a\nxx")})
    path = db.execute("SELECT path FROM employee_files WHERE employee_id=?", (a_emp,)).fetchone()["path"]
    assert c.get(f"/files/employee/{path}").status_code == 200
    row = db.execute("SELECT * FROM audit_logs WHERE action='employee_file_view'").fetchone()
    assert row and row["target_id"] == a_emp
