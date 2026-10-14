from tests.conftest import csrf


def _supplier(db, cid, code):
    return db.execute(
        "INSERT INTO partners (code, name, partner_type, company_id) VALUES (?,?, 'supplier', ?)", (code, code, cid)
    ).lastrowid


def _form(c, **kw):
    data = {"csrf_token": csrf(c, "/items/new"), "item_code": "M1", "item_name": "볼트", "purch_group": "자재1팀",
            "lead_days": "7", "moq": "100", "order_unit": "50", "reorder_pt": "30"}
    data.update(kw)
    return data


def test_item_purchase_fields(db, seed, login):
    pa = _supplier(db, seed["a"]["company"], "SA")
    db.commit()
    c = login("a_mgr")
    r = c.post("/items/save", data=_form(c, partner_id=str(pa)), follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT * FROM items WHERE item_code='M1'").fetchone()
    assert (row["partner_id"], row["purch_group"], row["lead_days"], row["moq"], row["order_unit"], row["reorder_pt"]) \
        == (pa, "자재1팀", 7, 100, 50, 30)
    html = c.get("/items").text
    assert "SA" in html
    edit = c.get(f"/items/{row['id']}/edit").text
    assert 'value="50"' in edit and f'value="{pa}" selected' in edit


def test_item_rejects_other_book_supplier(db, seed, login):
    pb = _supplier(db, seed["b"]["company"], "SB")
    db.commit()
    c = login("a_mgr")
    r = c.post("/items/save", data=_form(c, partner_id=str(pb)), follow_redirects=False)
    assert r.status_code == 400
    assert not db.execute("SELECT 1 FROM items WHERE item_code='M1'").fetchone()
    assert "SB" not in c.get("/items/new").text


def test_item_rejects_bad_order_unit(db, seed, login):
    c = login("a_mgr")
    r = c.post("/items/save", data=_form(c, order_unit="0"), follow_redirects=False)
    assert r.status_code == 400
