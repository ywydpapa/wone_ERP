from tests.conftest import csrf


def test_add_list_remove(login):
    c = login("a_mgr")
    r = c.post("/menu-favs", data={"csrf_token": csrf(c), "href": "/ledger/general", "label": "총계정원장"})
    assert r.json() == [{"href": "/ledger/general", "label": "총계정원장"}]
    t = c.get("/slip_list").text
    assert 'class="sidebar-link fav-link"' in t and "총계정원장</span>" in t
    r = c.request("DELETE", "/menu-favs", data={"csrf_token": csrf(c), "href": "/ledger/general"})
    assert r.json() == []
    assert c.get("/menu-favs").json() == []


def test_per_user(login):
    a = login("a_mgr")
    a.post("/menu-favs", data={"csrf_token": csrf(a), "href": "/slip_list", "label": "전표조회"})
    assert login("b_mgr").get("/menu-favs").json() == []


def test_rejects_external_and_limit(login):
    c = login("a_mgr")
    tok = csrf(c)
    for bad in ("//evil.com", "https://evil.com", "javascript:alert(1)"):
        assert c.post("/menu-favs", data={"csrf_token": tok, "href": bad, "label": "x"}).status_code == 400
    for n in range(20):
        c.post("/menu-favs", data={"csrf_token": tok, "href": f"/p{n}", "label": f"p{n}"})
    r = c.post("/menu-favs", data={"csrf_token": tok, "href": "/p20", "label": "p20"})
    assert r.status_code == 400 and "20개" in r.json()["error"]


def test_sidebar_has_menu_search(login):
    t = login("a_wk").get("/").text
    assert 'id="menuFind"' in t and 'id="modSwitch"' in t


def test_reorder_only_own(login):
    a, b = login("a_mgr"), login("b_mgr")
    tok = csrf(a)
    for href in ("/slip_list", "/ledger/general", "/partners"):
        a.post("/menu-favs", data={"csrf_token": tok, "href": href, "label": href})
    b.post("/menu-favs", data={"csrf_token": csrf(b), "href": "/slip_list", "label": "전표조회"})
    r = a.request("PATCH", "/menu-favs", data={"csrf_token": tok, "href": ["/partners", "/slip_list", "/ledger/general"]})
    assert [f["href"] for f in r.json()] == ["/partners", "/slip_list", "/ledger/general"]
    assert b.get("/menu-favs").json() == [{"href": "/slip_list", "label": "전표조회"}]


def test_menu_prefs_hide_groups(db, seed, login):
    c = login("a_mgr")
    r = c.put("/menu-prefs", data={"csrf_token": csrf(c), "hidden": ["fi", "mm", "bogus"], "user_id": str(seed["b"]["mgr"])})
    assert r.json() == {"hidden": ["fi", "mm"]}
    assert [tuple(r) for r in db.execute("SELECT user_id, hidden FROM menu_prefs")] == [(seed["a"]["mgr"], "fi,mm")]
    t = c.get("/slip_list").text
    assert 'sidebar-parent menu-off" data-menu="fi"' in t
    assert 'sidebar-parent" data-menu="sales"' in t
    # 숨긴 그룹 메뉴도 검색 대상이므로 링크는 그대로 렌더링
    assert 'href="/ledger/general"' in t
    assert 'menu-off" data-menu' not in login("b_mgr").get("/slip_list").text


def test_menu_prefs_default_all_visible(login):
    t = login("a_wk").get("/").text
    assert 'menu-off" data-menu' not in t and 'data-menu="fi"' in t
