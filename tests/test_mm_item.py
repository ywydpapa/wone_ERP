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


def test_item_nonstock_no_acct(db, seed, login):
    c = login("a_mgr")
    r = c.post("/items/save", data=_form(c, is_stock="0"), follow_redirects=False)
    assert r.status_code == 400
    assert not db.execute("SELECT 1 FROM items WHERE item_code='M1'").fetchone()


def test_item_nonstock_saved(db, seed, login):
    c = login("a_mgr")
    r = c.post("/items/save", data=_form(c, is_stock="0", account_code="821"), follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT is_stock, account_code FROM items WHERE item_code='M1'").fetchone()
    assert (row["is_stock"], row["account_code"]) == (0, "821")


def test_item_stock_acct_ignored(db, seed, login):
    c = login("a_mgr")
    r = c.post("/items/save", data=_form(c, is_stock="1", account_code="821"), follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT is_stock, account_code FROM items WHERE item_code='M1'").fetchone()
    assert (row["is_stock"], row["account_code"]) == (1, "")


def test_item_stock_flag_locked(db, seed, login):
    c = login("a_mgr")
    c.post("/items/save", data=_form(c), follow_redirects=False)
    item = db.execute("SELECT id FROM items WHERE item_code='M1'").fetchone()["id"]
    db.execute(
        "INSERT INTO stock_transactions (item_id, warehouse_id, trans_date, trans_type, quantity, ref_type, balance_qty) "
        "VALUES (?,1,'2026-10-01','in',5,'gr',5)", (item,),
    )
    db.commit()
    r = c.post("/items/save", data=_form(c, item_id=str(item), is_stock="0", account_code="821"), follow_redirects=False)
    assert r.status_code == 400
    assert db.execute("SELECT is_stock FROM items WHERE id=?", (item,)).fetchone()["is_stock"] == 1
