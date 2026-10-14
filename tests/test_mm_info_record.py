from tests.conftest import csrf


def _setup(db, cid, code):
    pid = db.execute(
        "INSERT INTO partners (code, name, partner_type, company_id) VALUES (?,?, 'supplier', ?)", (code, code, cid)
    ).lastrowid
    iid = db.execute(
        "INSERT INTO items (item_code, item_name, unit_price, company_id) VALUES (?,'볼트',100,?)", (code, cid)
    ).lastrowid
    db.commit()
    return pid, iid


def _save(c, pid, iid, **kw):
    data = {"csrf_token": csrf(c, f"/partners/{pid}/prices?kind=buy"), "kind": "buy", "item_id": str(iid),
            "price": "1,200"}
    data.update(kw)
    return c.post(f"/partners/{pid}/prices", data=data, follow_redirects=False)


def test_info_record_validity(db, seed, login):
    pid, iid = _setup(db, seed["a"]["company"], "A1")
    c = login("a_mgr")
    r = _save(c, pid, iid, valid_from="2026-10-01", valid_to="2026-12-31", lead_days="5")
    assert r.status_code == 303
    row = db.execute("SELECT price, valid_from, valid_to, lead_days FROM partner_prices").fetchone()
    assert tuple(row) == (1200, "2026-10-01", "2026-12-31", 5)
    assert c.get(f"/api/partners/{pid}/prices?kind=buy&on=2026-11-01").json() == {str(iid): 1200}
    assert c.get(f"/api/partners/{pid}/prices?kind=buy&on=2027-01-01").json() == {}
    assert c.get(f"/api/partners/{pid}/prices?kind=buy&on=2026-09-30").json() == {}
    assert "2026-12-31" in c.get(f"/partners/{pid}/prices?kind=buy").text


def test_info_record_open_period_and_sale_kept(db, seed, login):
    pid, iid = _setup(db, seed["a"]["company"], "A1")
    c = login("a_mgr")
    assert _save(c, pid, iid, valid_from="", valid_to="", lead_days="").status_code == 303
    assert c.get(f"/api/partners/{pid}/prices?kind=buy&on=2030-01-01").json() == {str(iid): 1200}
    assert _save(c, pid, iid, kind="sale", price="1500").status_code == 303
    assert c.get(f"/api/partners/{pid}/prices?kind=sale").json() == {str(iid): 1500}


def test_info_record_rejects_bad_period(db, seed, login):
    pid, iid = _setup(db, seed["a"]["company"], "A1")
    c = login("a_mgr")
    assert _save(c, pid, iid, valid_from="2026-12-01", valid_to="2026-11-01").status_code == 400
    assert _save(c, pid, iid, valid_from="2026-13-01").status_code == 400
    assert _save(c, pid, iid, lead_days="-1").status_code == 400
    assert not db.execute("SELECT 1 FROM partner_prices").fetchone()


def test_info_record_tenant(db, seed, login):
    pb, ib = _setup(db, seed["b"]["company"], "B1")
    pa, ia = _setup(db, seed["a"]["company"], "A1")
    b = login("b_mgr")
    assert _save(b, pb, ib).status_code == 303
    a = login("a_mgr")
    assert a.get(f"/api/partners/{pb}/prices?kind=buy").json() == {}
    assert a.get(f"/partners/{pb}/prices?kind=buy").status_code == 404
    assert _save(a, pb, ib).status_code == 400
    assert _save(a, pa, ib).status_code == 400
