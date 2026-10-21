from tests.conftest import csrf


def test_new_task_uses_selected_priority(db, seed, login):
    a = seed["a"]["company"]
    wr = db.execute(
        "INSERT INTO work_requests (company_id, title, task_type, status, priority) "
        "VALUES (?, '요청', 'erp', 'submitted', 'normal')", (a,),
    ).lastrowid
    db.commit()

    c = login("a_mgr")
    tok = csrf(c, f"/client/requests/{wr}")
    c.post(f"/client/requests/{wr}/tasks/new", data={
        "csrf_token": tok, "title": "긴급 업무", "priority": "urgent",
    }, follow_redirects=False)

    task = db.execute("SELECT priority FROM tasks WHERE work_request_id=?", (wr,)).fetchone()
    assert task["priority"] == "urgent"


def test_new_task_defaults_to_request_priority(db, seed, login):
    a = seed["a"]["company"]
    wr = db.execute(
        "INSERT INTO work_requests (company_id, title, task_type, status, priority) "
        "VALUES (?, '요청', 'erp', 'submitted', 'high')", (a,),
    ).lastrowid
    db.commit()

    c = login("a_mgr")
    tok = csrf(c, f"/client/requests/{wr}")
    c.post(f"/client/requests/{wr}/tasks/new", data={
        "csrf_token": tok, "title": "업무", "priority": "",
    }, follow_redirects=False)

    task = db.execute("SELECT priority FROM tasks WHERE work_request_id=?", (wr,)).fetchone()
    assert task["priority"] == "high"


def test_request_detail_shows_priority_select(db, seed, login):
    a = seed["a"]["company"]
    wr = db.execute(
        "INSERT INTO work_requests (company_id, title, task_type, status, priority) "
        "VALUES (?, '요청', 'erp', 'submitted', 'normal')", (a,),
    ).lastrowid
    db.commit()

    html = login("a_mgr").get(f"/client/requests/{wr}").text
    assert 'name="priority"' in html
    assert 'value="urgent"' in html
