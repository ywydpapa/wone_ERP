def _last_action(db, action):
    return db.execute(
        "SELECT * FROM audit_logs WHERE action=? ORDER BY id DESC LIMIT 1", (action,)
    ).fetchone()


def test_att_edit(db, seed, login):
    a = seed["a"]["company"]
    emp_id = db.execute("SELECT id FROM employees WHERE company_id=?", (a,)).fetchone()[0]
    att_id = db.execute(
        "INSERT INTO attendance (employee_id, work_date, status) VALUES (?, '2026-09-01', 'normal')",
        (emp_id,),
    ).lastrowid
    db.commit()

    c = login("t_staff")
    r = c.post(f"/hr/attendance/{att_id}/edit", data={"status": "late", "reason": "지연"}, follow_redirects=False)
    assert r.status_code == 303

    row = _last_action(db, "att_edit")
    assert row is not None
    assert row["target_type"] == "attendance"
    assert row["target_id"] == att_id
    assert row["company_id"] == a


def test_att_close(db, seed, login):
    a = seed["a"]["company"]
    db.execute("UPDATE users SET is_hr_admin=1 WHERE id=?", (seed["staff"],))
    db.commit()
    emp_id = db.execute("SELECT id FROM employees WHERE company_id=?", (a,)).fetchone()[0]

    c = login("t_staff")
    r = c.post(
        "/hr/attendance/close",
        data={"year": "2026", "month": "9", "company_id": str(a), "emp_ids": [str(emp_id)]},
        follow_redirects=False,
    )
    assert r.status_code == 303

    row = _last_action(db, "att_close")
    assert row is not None
    assert row["target_type"] == "attendance"
    assert row["company_id"] == a


def test_att_reopen(db, seed, login):
    a = seed["a"]["company"]
    closing_id = db.execute(
        "INSERT INTO attendance_closings (year, month, company_id, status) VALUES (2026,9,?,'closed')",
        (a,),
    ).lastrowid
    db.execute("UPDATE users SET is_hr_admin=1 WHERE id=?", (seed["staff"],))
    db.commit()

    c = login("t_staff")
    r = c.post(
        "/hr/attendance/reopen",
        data={"year": "2026", "month": "9", "company_id": str(a), "reopen_reason": "확인요청"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    row = _last_action(db, "att_reopen")
    assert row is not None
    assert row["target_type"] == "attendance"
    assert row["target_id"] == closing_id
    assert row["company_id"] == a


def _leave(db, a, wk):
    emp_id = db.execute("SELECT id FROM employees WHERE user_id=?", (wk,)).fetchone()[0]
    return db.execute(
        """INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, status)
           VALUES (?, 'annual', '2026-09-10', '2026-09-10', 1, 'pending')""",
        (emp_id,),
    ).lastrowid


def test_leave_approve(db, seed, login):
    a, wk = seed["a"]["company"], seed["a"]["wk"]
    leave_id = _leave(db, a, wk)
    db.commit()

    c = login("a_mgr")
    r = c.post(f"/client/leave/{leave_id}/approve", follow_redirects=False)
    assert r.status_code == 303

    row = _last_action(db, "leave_approve")
    assert row is not None
    assert row["target_type"] == "leave"
    assert row["target_id"] == leave_id
    assert row["company_id"] == a


def test_leave_reject(db, seed, login):
    a, wk = seed["a"]["company"], seed["a"]["wk"]
    leave_id = _leave(db, a, wk)
    db.commit()

    c = login("a_mgr")
    r = c.post(f"/client/leave/{leave_id}/reject", data={"reason": "사유없음"}, follow_redirects=False)
    assert r.status_code == 303

    row = _last_action(db, "leave_reject")
    assert row is not None
    assert row["target_type"] == "leave"
    assert row["target_id"] == leave_id
    assert row["company_id"] == a


def test_leave_cancel(db, seed, login):
    a, wk = seed["a"]["company"], seed["a"]["wk"]
    leave_id = _leave(db, a, wk)
    db.execute("UPDATE leave_requests SET status='approved' WHERE id=?", (leave_id,))
    db.commit()

    c = login("a_mgr")
    r = c.post(f"/client/leave/{leave_id}/cancel", follow_redirects=False)
    assert r.status_code == 303

    row = _last_action(db, "leave_cancel")
    assert row is not None
    assert row["target_type"] == "leave"
    assert row["target_id"] == leave_id
    assert row["company_id"] == a


def test_rate_update(db, seed, login):
    c = login("t_staff")
    r = c.post(
        "/hr/insurance-rates",
        data={"rate_key": "national_pension", "rate_value": "4.5", "effective_date": "2026-09-01"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    row = _last_action(db, "rate_update")
    assert row is not None
    assert row["target_type"] == "rate"


def _wo_setup(db, a, mgr):
    item = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('P-1','완제품',?)", (a,)
    ).lastrowid
    comp = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('C-1','부품',?)", (a,)
    ).lastrowid
    wh = db.execute(
        "INSERT INTO warehouses (code, name, company_id) VALUES ('W-A','창고A',?)", (a,)
    ).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,100)", (comp, wh))
    bom = db.execute(
        "INSERT INTO bom_headers (product_id, bom_version, created_by, company_id) VALUES (?,'1.0',?,?)",
        (item, mgr, a),
    ).lastrowid
    db.execute("INSERT INTO bom_lines (bom_id, component_id, quantity) VALUES (?,?,1)", (bom, comp))
    wo = db.execute(
        """INSERT INTO work_orders (wo_number, product_id, bom_id, planned_qty, created_by, company_id, status)
           VALUES ('WO-1', ?, ?, 10, ?, ?, 'planned')""",
        (item, bom, mgr, a),
    ).lastrowid
    db.commit()
    return wo, wh


def test_wo_release(db, seed, login):
    a, mgr = seed["a"]["company"], seed["a"]["mgr"]
    wo, wh = _wo_setup(db, a, mgr)

    c = login("a_mgr")
    r = c.post(f"/work-orders/{wo}/release", data={"warehouse_id": str(wh)}, follow_redirects=False)
    assert r.status_code == 303

    row = _last_action(db, "wo_release")
    assert row is not None
    assert row["target_type"] == "work_order"
    assert row["target_id"] == wo
    assert row["company_id"] == a


def test_wo_cancel(db, seed, login):
    a, mgr = seed["a"]["company"], seed["a"]["mgr"]
    wo, _ = _wo_setup(db, a, mgr)

    c = login("a_mgr")
    r = c.post(f"/work-orders/{wo}/cancel", follow_redirects=False)
    assert r.status_code == 303

    row = _last_action(db, "wo_cancel")
    assert row is not None
    assert row["target_type"] == "work_order"
    assert row["target_id"] == wo
    assert row["company_id"] == a


def test_company_update(db, seed, login):
    a = seed["a"]["company"]
    c = login("t_staff")
    r = c.post(
        f"/platform/companies/{a}",
        data={"name": "가테스트수정", "biz_type": "제조"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    row = _last_action(db, "company_update")
    assert row is not None
    assert row["target_type"] == "company"
    assert row["target_id"] == a
    assert row["company_id"] == a
    assert row["summary"] == "가테스트수정"
