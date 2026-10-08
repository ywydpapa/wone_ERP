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
