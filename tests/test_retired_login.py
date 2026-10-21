
def _resign(db, uid, d):
    db.execute("UPDATE employees SET status='retired', resign_date=? WHERE user_id=?", (d, uid))
    db.commit()


def test_retired_worker_cannot_login(db, seed, login):
    _resign(db, seed["a"]["wk"], "2020-01-31")
    c = login("a_wk")
    r = c.get("/mypage/leave", follow_redirects=False)
    assert r.status_code in (302, 303) and "/login" in r.headers["location"]
    row = db.execute("SELECT summary FROM audit_logs WHERE action='login_fail' AND user_id=?",
                     (seed["a"]["wk"],)).fetchone()
    assert row and "퇴사자" in row["summary"]


def test_resign_date_ahead_still_allowed(db, seed, login):
    _resign(db, seed["a"]["wk"], "2999-12-31")
    c = login("a_wk")
    assert c.get("/mypage/leave", follow_redirects=False).status_code == 200


def test_session_cut_after_resign(db, seed, login):
    c = login("a_wk")
    assert c.get("/mypage/leave", follow_redirects=False).status_code == 200
    _resign(db, seed["a"]["wk"], "2020-01-31")
    r = c.get("/mypage/leave", follow_redirects=False)
    assert "error=retired" in r.headers["location"]
    r = c.get("/mypage/leave", follow_redirects=False)
    assert "/login" in r.headers["location"]


def test_rehired_elsewhere_allowed(db, seed, login):
    _resign(db, seed["a"]["wk"], "2020-01-31")
    db.execute("INSERT INTO employees (user_id, name, company_id) VALUES (?,?,?)",
               (seed["a"]["wk"], "재입사", seed["b"]["company"]))
    db.commit()
    c = login("a_wk")
    assert c.get("/mypage/leave", follow_redirects=False).status_code == 200
