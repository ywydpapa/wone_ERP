from tests.conftest import csrf


def test_close_is_per_book(db, seed, login):
    m = login("a_mgr")
    r = m.post("/fi/closing/close", data={"csrf_token": csrf(m, "/fi/closing"), "year": "2026", "month": "8"}, follow_redirects=False)
    assert r.status_code in (200, 303)
    rows = db.execute("SELECT company_id FROM fi_closings WHERE year=2026 AND month=8 AND status='closed'").fetchall()
    assert [r["company_id"] for r in rows] == [seed["a"]["company"]]


def test_worker_cannot_close(db, seed, login):
    w = login("a_wk")
    r = w.post("/fi/closing/close", data={"csrf_token": csrf(w, "/fi/closing"), "year": "2026", "month": "8"}, follow_redirects=False)
    assert r.status_code == 403


def test_budget_per_book(db, seed, login):
    m = login("a_mgr")
    m.post("/budget/save", data={"csrf_token": csrf(m, "/budget/edit"), "year": "2026", "b_813_1": "10000"}, follow_redirects=False)
    assert db.execute("SELECT company_id FROM budgets").fetchone()["company_id"] == seed["a"]["company"]
