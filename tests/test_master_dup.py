from tests.conftest import csrf


def test_dup_codes_rejected(db, seed, login):
    c = login("a_mgr")
    cases = [
        ("/items/save", "/items/new", {"item_code": "M1", "item_name": "볼트"}),
        ("/warehouses/save", "/warehouses/new", {"code": "W1", "name": "본창고"}),
        ("/memo-codes/save", "/memo-codes/new", {"code": "101", "text": "현금 입금"}),
        ("/bank-accounts/save", "/bank-accounts/new",
         {"bank": "국민은행", "account_no": "123", "name": "보통예금", "account_code": "103"}),
    ]
    for url, form, data in cases:
        r = c.post(url, data={"csrf_token": csrf(c, form), **data}, follow_redirects=False)
        assert r.status_code == 303, url
        r = c.post(url, data={"csrf_token": csrf(c, form), **data}, follow_redirects=False)
        assert r.status_code == 400, url


def test_company_schedule(db, seed, login):
    c = login("t_staff")
    r = c.post("/platform/companies", data={
        "csrf_token": csrf(c, "/platform/companies/new"),
        "name": "스케줄테스트", "start_time": "08:30", "end_time": "17:30", "break_min": "50",
        "rest_day": "0", "off_day": "6", "employee_count": "12",
    }, follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT id, employee_count FROM client_companies WHERE name='스케줄테스트'").fetchone()
    assert row["employee_count"] == 12
    s = db.execute("SELECT * FROM work_schedules WHERE company_id=?", (row["id"],)).fetchone()
    assert (s["start_time"], s["end_time"], s["break_min"], s["rest_day"], s["off_day"]) == ("08:30", "17:30", 50, 0, 6)


def test_profile_links(db, seed, login):
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (seed["a"]["company"],))
    eid = db.execute(
        "INSERT INTO employees (name, company_id, status) VALUES ('역량', ?, 'active')", (seed["a"]["company"],)
    ).lastrowid
    db.commit()
    c = login("t_staff")
    html = c.get(f"/hr/employees/{eid}").text
    assert f"/hr/employees/{eid}/profile" in html
    assert "/capability" not in c.get(f"/hr/employees/{eid}/profile").text
