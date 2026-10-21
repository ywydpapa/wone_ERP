def test_hr_employee_edit_logs_resident_no_view(db, seed, login):
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (seed["a"]["company"],))
    db.commit()
    company = seed["a"]["company"]
    emp_id = db.execute(
        "INSERT INTO employees (name, company_id, resident_no, status) VALUES (?,?,?,'active')",
        ("주민번호테스트", company, "900101-1234567"),
    ).lastrowid
    db.commit()

    c = login("t_staff")
    assert c.get(f"/hr/employees/{emp_id}/edit").status_code == 200

    row = db.execute(
        "SELECT * FROM audit_logs WHERE action='resident_no_view' AND target_id=?", (emp_id,)
    ).fetchone()
    assert row is not None


def test_client_hr_edit_logs_resident_no_view(db, seed, login):
    company = seed["a"]["company"]
    emp_id = db.execute(
        "INSERT INTO employees (name, company_id, resident_no, status) VALUES (?,?,?,'active')",
        ("주민번호클라", company, "900101-2234567"),
    ).lastrowid
    db.commit()

    c = login("a_mgr")
    assert c.get(f"/client/workers/{emp_id}/edit").status_code == 200

    row = db.execute(
        "SELECT * FROM audit_logs WHERE action='resident_no_view' AND target_id=?", (emp_id,)
    ).fetchone()
    assert row is not None


def test_no_log_when_resident_no_blank(db, seed, login):
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (seed["a"]["company"],))
    db.commit()
    company = seed["a"]["company"]
    emp_id = db.execute(
        "INSERT INTO employees (name, company_id, status) VALUES (?,?,'active')",
        ("주민번호없음", company),
    ).lastrowid
    db.commit()

    c = login("t_staff")
    assert c.get(f"/hr/employees/{emp_id}/edit").status_code == 200
    assert not db.execute(
        "SELECT 1 FROM audit_logs WHERE action='resident_no_view' AND target_id=?", (emp_id,)
    ).fetchone()


def test_list_view_does_not_log(db, seed, login):
    company = seed["a"]["company"]
    db.execute(
        "INSERT INTO employees (name, company_id, resident_no, status) VALUES (?,?,?,'active')",
        ("목록전용", company, "900101-3234567"),
    )
    db.commit()

    c = login("t_staff")
    assert c.get("/hr/employees").status_code == 200
    assert not db.execute("SELECT 1 FROM audit_logs WHERE action='resident_no_view'").fetchone()
