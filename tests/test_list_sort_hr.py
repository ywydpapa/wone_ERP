def _emp_id(db, user_id):
    return db.execute("SELECT id FROM employees WHERE user_id=?", (user_id,)).fetchone()[0]


def test_employee_list_sort(db, seed, login):
    db.execute("INSERT INTO employees (name, employee_no, company_id) VALUES ('가나다', 'E100', NULL)")
    db.execute("INSERT INTO employees (name, employee_no, company_id) VALUES ('하하하', 'E200', NULL)")
    db.commit()

    c = login("t_staff")
    asc = c.get("/hr/employees?sort=name&dir=asc").text
    desc = c.get("/hr/employees?sort=name&dir=desc").text
    assert asc.index("가나다") < asc.index("하하하")
    assert desc.index("하하하") < desc.index("가나다")
    assert c.get("/hr/employees?sort=1;DROP").status_code == 200

    csv = c.get("/hr/employees?export=csv")
    assert "csv" in csv.headers["content-type"]
    body = csv.content.decode("utf-8-sig")
    assert "가나다" in body and "하하하" in body
    assert "resident_no" not in body and "bank_account" not in body


def test_hr_appeal_list_sort(db, seed, login):
    eid_a = _emp_id(db, seed["a"]["wk"])
    db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, appeal, appeal_reason) VALUES (?,?,?,?,?)",
        (eid_a, "2026-09-05", "late", "pending", "소명1"),
    )
    db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, appeal, appeal_reason) VALUES (?,?,?,?,?)",
        (eid_a, "2026-09-20", "late", "pending", "소명2"),
    )
    db.commit()

    c = login("t_staff")
    asc = c.get("/hr/attendance/appeals?sort=date&dir=asc").text
    desc = c.get("/hr/attendance/appeals?sort=date&dir=desc").text
    assert asc.index("2026-09-05") < asc.index("2026-09-20")
    assert desc.index("2026-09-20") < desc.index("2026-09-05")
    assert c.get("/hr/attendance/appeals?sort=1;DROP").status_code == 200

    csv = c.get("/hr/attendance/appeals?export=csv")
    assert "csv" in csv.headers["content-type"]


def test_hr_certificate_list_sort(db, seed, login):
    eid_a = _emp_id(db, seed["a"]["wk"])
    db.execute(
        "INSERT INTO certificate_requests (employee_id, cert_type, requested_at) VALUES (?,?,?)",
        (eid_a, "재직증명서", "2026-09-01 10:00:00"),
    )
    db.execute(
        "INSERT INTO certificate_requests (employee_id, cert_type, requested_at) VALUES (?,?,?)",
        (eid_a, "경력증명서", "2026-09-10 10:00:00"),
    )
    db.commit()

    c = login("t_staff")
    asc = c.get("/hr/certificates?sort=date&dir=asc").text
    desc = c.get("/hr/certificates?sort=date&dir=desc").text
    assert asc.index("재직증명서") < asc.index("경력증명서")
    assert desc.index("경력증명서") < desc.index("재직증명서")
    assert c.get("/hr/certificates?sort=1;DROP").status_code == 200

    csv = c.get("/hr/certificates?export=csv")
    assert "csv" in csv.headers["content-type"]


def test_severance_estimate_list_sort(db, seed, login):
    db.execute(
        "INSERT INTO employees (name, company_id, hire_date, status, base_salary) "
        "VALUES ('내부1', NULL, '2010-01-01', 'active', 3000000)"
    )
    db.execute(
        "INSERT INTO employees (name, company_id, hire_date, status, base_salary) "
        "VALUES ('내부2', NULL, '2023-06-01', 'active', 3000000)"
    )
    db.commit()

    c = login("t_staff")
    asc = c.get("/severance/estimate?base_date=2026-10-01&sort=hire&dir=asc").text
    desc = c.get("/severance/estimate?base_date=2026-10-01&sort=hire&dir=desc").text
    assert asc.index("2010-01-01") < asc.index("2023-06-01")
    assert desc.index("2023-06-01") < desc.index("2010-01-01")
    assert c.get("/severance/estimate?sort=1;DROP").status_code == 200

    csv = c.get("/severance/estimate?base_date=2026-10-01&export=csv")
    assert "csv" in csv.headers["content-type"]


def test_audit_list_sort(db, seed, login):
    db.execute(
        "INSERT INTO audit_logs (at, user_name, role, action, summary) VALUES (?,?,?,?,?)",
        ("2026-09-10 09:00:00", "aaa사용자", "platform_staff", "login", "로그인"),
    )
    db.execute(
        "INSERT INTO audit_logs (at, user_name, role, action, summary) VALUES (?,?,?,?,?)",
        ("2026-09-10 09:10:00", "zzz사용자", "platform_staff", "login", "로그인"),
    )
    db.commit()

    c = login("t_staff")
    q = "start=2026-09-01&end=2026-09-30"
    asc = c.get(f"/audit?{q}&sort=user&dir=asc").text
    desc = c.get(f"/audit?{q}&sort=user&dir=desc").text
    assert asc.index("aaa사용자") < asc.index("zzz사용자")
    assert desc.index("zzz사용자") < desc.index("aaa사용자")
    assert c.get(f"/audit?{q}&sort=1;DROP").status_code == 200


def test_user_list_sort(db, seed, login):
    c = login("t_staff")
    asc = c.get("/users?sort=name&dir=asc").text
    desc = c.get("/users?sort=name&dir=desc").text
    names = ["가테스트담당", "나테스트담당"]
    assert asc.index(names[0]) < asc.index(names[1])
    assert desc.index(names[1]) < desc.index(names[0])
    assert c.get("/users?sort=1;DROP").status_code == 200

    csv = c.get("/users?export=csv")
    assert "csv" in csv.headers["content-type"]


def test_client_leave_list_sort(db, seed, login):
    eid_a = _emp_id(db, seed["a"]["wk"])
    eid_b = _emp_id(db, seed["b"]["wk"])
    db.execute(
        "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, status) "
        "VALUES (?, 'annual', '2026-09-05', '2026-09-05', 1, 'pending')", (eid_a,),
    )
    db.execute(
        "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, status) "
        "VALUES (?, 'annual', '2026-09-20', '2026-09-20', 1, 'pending')", (eid_a,),
    )
    db.execute(
        "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, status) "
        "VALUES (?, 'annual', '2026-09-15', '2026-09-15', 1, 'pending')", (eid_b,),
    )
    db.commit()

    c = login("a_mgr")
    asc = c.get("/client/leave?sort=start&dir=asc").text
    desc = c.get("/client/leave?sort=start&dir=desc").text
    assert asc.index("2026-09-05") < asc.index("2026-09-20")
    assert desc.index("2026-09-20") < desc.index("2026-09-05")
    assert c.get("/client/leave?sort=1;DROP").status_code == 200

    csv = c.get("/client/leave?export=csv")
    assert "csv" in csv.headers["content-type"]
    body = csv.content.decode("utf-8-sig")
    assert "2026-09-05" in body and "2026-09-20" in body
    assert "2026-09-15" not in body


def test_client_accom_list_sort(db, seed, login):
    eid_a = _emp_id(db, seed["a"]["wk"])
    eid_b = _emp_id(db, seed["b"]["wk"])
    db.execute(
        "INSERT INTO accommodation_requests (employee_id, category, title, urgency, status) "
        "VALUES (?, 'equipment', 'A요청', 'normal', 'pending')", (eid_a,),
    )
    db.execute(
        "INSERT INTO accommodation_requests (employee_id, category, title, urgency, status) "
        "VALUES (?, 'equipment', 'Z요청', 'normal', 'pending')", (eid_a,),
    )
    db.execute(
        "INSERT INTO accommodation_requests (employee_id, category, title, urgency, status) "
        "VALUES (?, 'equipment', 'B사요청', 'normal', 'pending')", (eid_b,),
    )
    db.commit()

    c = login("a_mgr")
    asc = c.get("/client/accommodation?sort=name&dir=asc").text
    assert "A요청" in asc and "B사요청" not in asc
    assert c.get("/client/accommodation?sort=1;DROP").status_code == 200

    csv = c.get("/client/accommodation?export=csv")
    assert "csv" in csv.headers["content-type"]
    body = csv.content.decode("utf-8-sig")
    assert "A요청" in body and "Z요청" in body
    assert "B사요청" not in body


def test_client_cert_list_sort(db, seed, login):
    eid_a = _emp_id(db, seed["a"]["wk"])
    eid_b = _emp_id(db, seed["b"]["wk"])
    db.execute(
        "INSERT INTO certificate_requests (employee_id, cert_type, requested_at) VALUES (?,?,?)",
        (eid_a, "재직증명서", "2026-09-01 10:00:00"),
    )
    db.execute(
        "INSERT INTO certificate_requests (employee_id, cert_type, requested_at) VALUES (?,?,?)",
        (eid_b, "경력증명서", "2026-09-10 10:00:00"),
    )
    db.commit()

    c = login("a_mgr")
    body = c.get("/client/certificates?sort=type&dir=asc").text
    assert "재직증명서" in body and "경력증명서" not in body
    assert c.get("/client/certificates?sort=1;DROP").status_code == 200

    csv = c.get("/client/certificates?export=csv")
    assert "csv" in csv.headers["content-type"]
    body = csv.content.decode("utf-8-sig")
    assert "재직증명서" in body and "경력증명서" not in body


def test_client_appeal_list_sort(db, seed, login):
    eid_a = _emp_id(db, seed["a"]["wk"])
    db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, appeal, appeal_reason) VALUES (?,?,?,?,?)",
        (eid_a, "2026-09-05", "late", "pending", "소명1"),
    )
    db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, appeal, appeal_reason) VALUES (?,?,?,?,?)",
        (eid_a, "2026-09-20", "late", "pending", "소명2"),
    )
    db.commit()

    c = login("a_mgr")
    asc = c.get("/client/attendance/appeals?sort=date&dir=asc").text
    desc = c.get("/client/attendance/appeals?sort=date&dir=desc").text
    assert asc.index("2026-09-05") < asc.index("2026-09-20")
    assert desc.index("2026-09-20") < desc.index("2026-09-05")
    assert c.get("/client/attendance/appeals?sort=1;DROP").status_code == 200

    csv = c.get("/client/attendance/appeals?export=csv")
    assert "csv" in csv.headers["content-type"]


def test_client_eval_list_sort(db, seed, login):
    eid_a = _emp_id(db, seed["a"]["wk"])
    eid_b = _emp_id(db, seed["b"]["wk"])
    db.execute(
        "INSERT INTO worker_evaluations (employee_id, company_id, eval_year, eval_quarter, overall_score) "
        "VALUES (?,?,2026,1,2.0)", (eid_a, seed["a"]["company"]),
    )
    db.execute(
        "INSERT INTO worker_evaluations (employee_id, company_id, eval_year, eval_quarter, overall_score) "
        "VALUES (?,?,2026,2,4.5)", (eid_a, seed["a"]["company"]),
    )
    db.execute(
        "INSERT INTO worker_evaluations (employee_id, company_id, eval_year, eval_quarter, overall_score) "
        "VALUES (?,?,2026,1,3.0)", (eid_b, seed["b"]["company"]),
    )
    db.commit()

    c = login("a_mgr")
    asc = c.get("/client/evaluations?sort=overall&dir=asc").text
    desc = c.get("/client/evaluations?sort=overall&dir=desc").text
    assert asc.index("2.0") < asc.index("4.5")
    assert desc.index("4.5") < desc.index("2.0")
    assert c.get("/client/evaluations?sort=1;DROP").status_code == 200

    csv = c.get("/client/evaluations?export=csv")
    assert "csv" in csv.headers["content-type"]
    body = csv.content.decode("utf-8-sig")
    assert "2.0" in body and "4.5" in body
    assert "3.0" not in body


def test_client_request_list_sort(db, seed, login):
    db.execute(
        "INSERT INTO work_requests (company_id, title, task_type, due_date, status) "
        "VALUES (?, 'A요청', 'entry', '2026-09-05', 'submitted')", (seed["a"]["company"],),
    )
    db.execute(
        "INSERT INTO work_requests (company_id, title, task_type, due_date, status) "
        "VALUES (?, 'Z요청', 'entry', '2026-09-20', 'submitted')", (seed["a"]["company"],),
    )
    db.execute(
        "INSERT INTO work_requests (company_id, title, task_type, due_date, status) "
        "VALUES (?, 'B사요청', 'entry', '2026-09-10', 'submitted')", (seed["b"]["company"],),
    )
    db.commit()

    c = login("a_mgr")
    asc = c.get("/client/requests?sort=title&dir=asc").text
    assert "A요청" in asc and "B사요청" not in asc
    assert c.get("/client/requests?sort=1;DROP").status_code == 200

    csv = c.get("/client/requests?export=csv")
    assert "csv" in csv.headers["content-type"]
    body = csv.content.decode("utf-8-sig")
    assert "A요청" in body and "Z요청" in body
    assert "B사요청" not in body
