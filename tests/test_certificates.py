def test_employee_request_starts_pending(db, seed, login):
    c = login("a_wk")
    r = c.post("/mypage/certificates", data={"cert_type": "재직증명서", "purpose": "은행제출용"}, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT * FROM certificate_requests ORDER BY id DESC LIMIT 1").fetchone()
    assert row["status"] == "pending"
    assert row["cert_number"] is None


def test_income_certificate_keeps_instant_complete_without_print(db, seed, login):
    c = login("a_wk")
    r = c.post("/mypage/certificates", data={"cert_type": "소득금액증명", "purpose": "기타"}, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT * FROM certificate_requests ORDER BY id DESC LIMIT 1").fetchone()
    assert row["status"] == "completed"
    assert row["cert_number"]

    r = c.get(f"/mypage/certificates/{row['id']}/print")
    assert r.status_code == 404


def test_cannot_print_before_issued(db, seed, login):
    emp_a = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    cert_id = db.execute(
        "INSERT INTO certificate_requests (employee_id, cert_type, purpose, status) VALUES (?,?,?,'pending')",
        (emp_a, "재직증명서", "은행제출용"),
    ).lastrowid
    db.commit()

    c = login("a_wk")
    r = c.get(f"/mypage/certificates/{cert_id}/print")
    assert r.status_code == 404


def test_client_hr_issue_and_employee_print(db, seed, login):
    emp_a = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    cert_id = db.execute(
        "INSERT INTO certificate_requests (employee_id, cert_type, purpose, status) VALUES (?,?,?,'pending')",
        (emp_a, "재직증명서", "은행제출용"),
    ).lastrowid
    db.commit()

    hr = login("a_mgr")
    r = hr.post(f"/client/certificates/{cert_id}/issue", follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT * FROM certificate_requests WHERE id=?", (cert_id,)).fetchone()
    assert row["status"] == "completed"
    assert row["cert_number"]
    assert row["issued_by"]

    emp = login("a_wk")
    r = emp.get(f"/mypage/certificates/{cert_id}/print")
    assert r.status_code == 200
    assert "재직증명서" in r.text
    assert row["cert_number"] in r.text


def test_other_company_hr_cannot_issue(db, seed, login):
    emp_a = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    cert_id = db.execute(
        "INSERT INTO certificate_requests (employee_id, cert_type, purpose, status) VALUES (?,?,?,'pending')",
        (emp_a, "재직증명서", "은행제출용"),
    ).lastrowid
    db.commit()

    hr_b = login("b_mgr")
    r = hr_b.post(f"/client/certificates/{cert_id}/issue")
    assert r.status_code == 404

    row = db.execute("SELECT status FROM certificate_requests WHERE id=?", (cert_id,)).fetchone()
    assert row["status"] == "pending"


def test_other_employee_cannot_print(db, seed, login):
    emp_a = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    cert_id = db.execute(
        "INSERT INTO certificate_requests (employee_id, cert_type, purpose, status, cert_number, completed_at) "
        "VALUES (?,?,?,'completed','CERT-TEST-0001', datetime('now'))",
        (emp_a, "재직증명서", "은행제출용"),
    ).lastrowid
    db.commit()

    other = login("b_wk")
    r = other.get(f"/mypage/certificates/{cert_id}/print")
    assert r.status_code == 404


def test_staff_can_issue_and_print(db, seed, login):
    emp_a = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    cert_id = db.execute(
        "INSERT INTO certificate_requests (employee_id, cert_type, purpose, status) VALUES (?,?,?,'pending')",
        (emp_a, "경력증명서", "기타"),
    ).lastrowid
    db.commit()

    staff = login("t_staff")
    r = staff.get("/hr/certificates")
    assert r.status_code == 200

    r = staff.post(f"/hr/certificates/{cert_id}/issue", follow_redirects=False)
    assert r.status_code == 303

    r = staff.get(f"/hr/certificates/{cert_id}/print")
    assert r.status_code == 200
    assert "경력증명서" in r.text
