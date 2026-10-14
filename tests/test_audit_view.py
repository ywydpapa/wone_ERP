from core.tz import today_kst


def _row(db, company_id, action="login", target_type="user", summary="테스트"):
    at = today_kst().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """INSERT INTO audit_logs (at, user_id, user_name, role, company_id, action, target_type, target_id, summary)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (at, 1, "테스트유저", "client", company_id, action, target_type, 1, summary),
    )
    db.commit()


def test_client_sees_own_company_only(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    _row(db, a, summary="A사 로그")
    _row(db, b, summary="B사 로그")
    c = login("a_mgr")
    r = c.get("/audit")
    assert r.status_code == 200
    assert "A사 로그" in r.text
    assert "B사 로그" not in r.text


def test_staff_sees_all_companies(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    _row(db, a, summary="A사 로그")
    _row(db, b, summary="B사 로그")
    c = login("t_staff")
    r = c.get("/audit")
    assert r.status_code == 200
    assert "A사 로그" in r.text
    assert "B사 로그" in r.text


def test_worker_forbidden(db, seed, login):
    c = login("a_wk")
    r = c.get("/audit")
    assert r.status_code == 403


def test_action_prefix_filter(db, seed, login):
    a = seed["a"]["company"]
    _row(db, a, action="login", summary="로그인행")
    _row(db, a, action="login_fail", summary="로그인실패행")
    _row(db, a, action="post", summary="전기행")
    c = login("a_mgr")
    r = c.get("/audit?action=login")
    assert "로그인행" in r.text
    assert "로그인실패행" in r.text
    assert "전기행" not in r.text


def test_csv_respects_company_scope(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    _row(db, a, summary="A사 로그")
    _row(db, b, summary="B사 로그")
    c = login("a_mgr")
    r = c.get("/audit/csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    body = r.content.decode("utf-8-sig")
    assert "A사 로그" in body
    assert "B사 로그" not in body
