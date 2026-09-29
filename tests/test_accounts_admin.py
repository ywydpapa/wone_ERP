from tests.conftest import csrf


def test_add_and_toggle(db, seed, login):
    m = login("a_mgr")
    tok = csrf(m, "/fi/accounts")
    r = m.post("/fi/accounts", data={"csrf_token": tok, "code": "825", "name": "교육비", "category": "비용"}, follow_redirects=False)
    assert r.status_code == 303
    a = seed["a"]["company"]
    assert db.execute("SELECT is_debit FROM accounts WHERE company_id=? AND code='825'", (a,)).fetchone()[0] == 1
    assert not db.execute("SELECT 1 FROM accounts WHERE company_id=? AND code='825'", (seed["b"]["company"],)).fetchone()
    assert m.post("/fi/accounts", data={"csrf_token": tok, "code": "825", "name": "중복", "category": "비용"}).status_code == 400
    assert m.post("/fi/accounts", data={"csrf_token": tok, "code": "826", "name": "틀림", "category": "자산"}).status_code == 400
    m.post("/fi/accounts/825", data={"csrf_token": tok, "name": "교육비", "is_active": "0", "req_partner": "0", "req_dept": "1"}, follow_redirects=False)
    row = db.execute("SELECT is_active, req_dept FROM accounts WHERE company_id=? AND code='825'", (a,)).fetchone()
    assert tuple(row) == (0, 1)


def test_worker_readonly(db, seed, login):
    w = login("a_wk")
    assert w.get("/fi/accounts").status_code == 200
    assert w.post("/fi/accounts", data={"csrf_token": csrf(w, "/fi/accounts"), "code": "825", "name": "x", "category": "비용"}).status_code == 403
