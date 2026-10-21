MARK = "B-ITEM-DETAIL-SECRET"


def test_item_detail_shows_stock_and_moves(db, seed, login):
    a = seed["a"]["company"]
    item = db.execute(
        "INSERT INTO items (item_code, item_name, company_id, reorder_pt) VALUES ('IT1','볼트',?,10)", (a,)
    ).lastrowid
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','본사창고',?)", (a,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,5)", (item, wh))
    db.execute(
        "INSERT INTO stock_transactions (item_id, warehouse_id, trans_date, trans_type, quantity, ref_type, balance_qty) "
        "VALUES (?,?,'2026-10-01','in',5,'gr',5)", (item, wh),
    )
    db.commit()

    html = login("a_mgr").get(f"/items/{item}").text
    assert "볼트" in html
    assert "본사창고" in html
    assert "입고" in html


def test_item_detail_blocks_other_company(db, seed, login):
    b = seed["b"]["company"]
    item = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('IT2',?,?)", (MARK, b)
    ).lastrowid
    db.commit()

    r = login("a_mgr").get(f"/items/{item}", follow_redirects=False)
    assert r.status_code == 303
    assert MARK not in r.text


def test_item_list_links_to_detail_not_edit(db, seed, login):
    a = seed["a"]["company"]
    item = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('IT3','너트',?)", (a,)
    ).lastrowid
    db.commit()

    html = login("a_mgr").get("/items").text
    assert f'href="/items/{item}"' in html
    assert f'href="/items/{item}/edit"' not in html


def test_item_detail_shows_partner_price(db, seed, login):
    a = seed["a"]["company"]
    item = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('IT4','너트2',?)", (a,)
    ).lastrowid
    p = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('PP1','가격거래처',?,'supplier')", (a,)
    ).lastrowid
    db.execute(
        "INSERT INTO partner_prices (company_id, partner_id, item_id, kind, price) VALUES (?,?,?,'buy',1500)",
        (a, p, item),
    )
    db.commit()

    html = login("a_mgr").get(f"/items/{item}").text
    assert "가격거래처" in html
    assert "1,500" in html


def test_item_detail_shows_bom_relations(db, seed, login):
    a = seed["a"]["company"]
    product = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('PR1','완제품',?)", (a,)
    ).lastrowid
    part = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('PT1','부품',?)", (a,)
    ).lastrowid
    bom = db.execute(
        "INSERT INTO bom_headers (product_id, company_id) VALUES (?,?)", (product, a)
    ).lastrowid
    db.execute(
        "INSERT INTO bom_lines (bom_id, component_id, quantity, unit) VALUES (?,?,2,'EA')", (bom, part)
    )
    db.commit()

    html_product = login("a_mgr").get(f"/items/{product}").text
    assert "부품" in html_product

    html_part = login("a_mgr").get(f"/items/{part}").text
    assert "완제품" in html_part


def test_item_detail_bom_hides_other_company(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    part_a = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('PT2','부품A',?)", (a,)
    ).lastrowid
    product_b = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('PR2',?,?)", (MARK, b)
    ).lastrowid
    part_b = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES ('PT3','부품B',?)", (b,)
    ).lastrowid
    bom = db.execute(
        "INSERT INTO bom_headers (product_id, company_id) VALUES (?,?)", (product_b, b)
    ).lastrowid
    db.execute(
        "INSERT INTO bom_lines (bom_id, component_id, quantity, unit) VALUES (?,?,1,'EA')", (bom, part_b)
    )
    db.commit()

    html = login("a_mgr").get(f"/items/{part_a}").text
    assert MARK not in html
