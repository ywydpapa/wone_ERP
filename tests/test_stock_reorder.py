MARK = "B-REORDER-SECRET"


def test_reorder_list_shows_item_below_point(db, seed, login):
    a = seed["a"]["company"]
    item = db.execute(
        "INSERT INTO items (item_code, item_name, company_id, reorder_pt, moq, order_unit) "
        "VALUES ('RE1','볼트',?,10,20,5)", (a,)
    ).lastrowid
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','창고',?)", (a,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,3)", (item, wh))
    db.commit()

    html = login("a_mgr").get("/stock/reorder").text
    assert "볼트" in html
    # 재발주점(10)-현재고(3)=7, 최소발주량 20 우선, 발주단위 5 배수이므로 변경 없음
    assert f"item_id={item}" in html
    assert "qty=20" in html


def test_reorder_list_excludes_item_above_point(db, seed, login):
    a = seed["a"]["company"]
    db.execute(
        "INSERT INTO items (item_code, item_name, company_id, reorder_pt) VALUES ('RE2','충분재고',?,10)", (a,)
    )
    item = db.execute("SELECT id FROM items WHERE item_code='RE2'").fetchone()[0]
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W2','창고2',?)", (a,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,50)", (item, wh))
    db.commit()

    html = login("a_mgr").get("/stock/reorder").text
    assert "충분재고" not in html


def test_reorder_list_hides_other_company(db, seed, login):
    b = seed["b"]["company"]
    db.execute(
        "INSERT INTO items (item_code, item_name, company_id, reorder_pt) VALUES ('RE3',?,?,10)", (MARK, b)
    )
    item = db.execute("SELECT id FROM items WHERE item_code='RE3'").fetchone()[0]
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W3','창고3',?)", (b,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,1)", (item, wh))
    db.commit()

    html = login("a_mgr").get("/stock/reorder").text
    assert MARK not in html


def test_pr_form_prefills_own_item_only(db, seed, login):
    a = seed["a"]["company"]
    b = seed["b"]["company"]
    mine = db.execute(
        "INSERT INTO items (item_code, item_name, company_id, unit_price) VALUES ('RE4','너트',?,500)", (a,)
    ).lastrowid
    other = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('RE5',?,?)", (MARK, b)
    ).lastrowid
    db.commit()

    c = login("a_mgr")
    html = c.get(f"/purchase-requisitions/new?item_id={mine}&qty=20").text
    assert f"addLine({mine}, " in html and ", 20, 500, '')" in html
    assert MARK not in c.get(f"/purchase-requisitions/new?item_id={other}&qty=5").text
