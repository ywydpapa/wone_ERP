MARK = "B-PRINT-SECRET"


def _partner(db, company_id, name="거래처"):
    return db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES (?,?,?,'both')",
        (f"P{name}", name, company_id),
    ).lastrowid


def _item(db, company_id, code, name):
    return db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES (?,?,?)", (code, name, company_id)
    ).lastrowid


def test_quote_print_shows_title_and_company(db, seed, login):
    a = seed["a"]["company"]
    p = _partner(db, a, "견적거래처")
    it = _item(db, a, "QT1", "품목A")
    qt = db.execute(
        "INSERT INTO quotations (quote_number, partner_id, quote_date, company_id, total_amount, tax_amount) "
        "VALUES ('QT-2026-0001',?,'2026-10-01',?,10000,1000)", (p, a),
    ).lastrowid
    db.execute(
        "INSERT INTO quote_lines (quote_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,10,1000,10000)",
        (qt, it),
    )
    db.commit()

    html = login("a_mgr").get(f"/quotations/{qt}/print").text
    assert "견적서" in html
    assert "견적거래처" in html
    assert "품목A" in html


def test_quote_print_blocks_other_company(db, seed, login):
    b = seed["b"]["company"]
    p = _partner(db, b, MARK)
    qt = db.execute(
        "INSERT INTO quotations (quote_number, partner_id, quote_date, company_id) VALUES ('QT-2026-9999',?,'2026-10-01',?)",
        (p, b),
    ).lastrowid
    db.commit()

    r = login("a_mgr").get(f"/quotations/{qt}/print", follow_redirects=False)
    assert r.status_code == 303
    assert MARK not in r.text


def test_shipment_print_shows_outbound_title(db, seed, login):
    a = seed["a"]["company"]
    p = _partner(db, a, "출고거래처")
    it = _item(db, a, "SH1", "품목B")
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','창고',?)", (a,)).lastrowid
    so = db.execute(
        "INSERT INTO sales_orders (so_number, partner_id, order_date, company_id) VALUES ('SO-1',?,'2026-10-01',?)",
        (p, a),
    ).lastrowid
    sol = db.execute(
        "INSERT INTO so_lines (so_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,5,2000,10000)",
        (so, it),
    ).lastrowid
    ship = db.execute(
        "INSERT INTO shipments (ship_number, so_id, warehouse_id, ship_date, company_id) VALUES ('SHP-1',?,?,'2026-10-02',?)",
        (so, wh, a),
    ).lastrowid
    db.execute(
        "INSERT INTO ship_lines (ship_id, so_line_id, item_id, shipped_qty) VALUES (?,?,?,5)", (ship, sol, it)
    )
    db.commit()

    html = login("a_mgr").get(f"/shipments/{ship}/print").text
    assert "출 고 증" in html
    assert "출고거래처" in html
    assert "품목B" in html
    assert "10,000" in html
    # 출고증은 부가세 구분 없이 합계 한 줄만
    assert "부가세" not in html


def test_gr_print_shows_inbound_title(db, seed, login):
    a = seed["a"]["company"]
    p = _partner(db, a, "입고거래처")
    it = _item(db, a, "GR1", "품목C")
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W2','창고2',?)", (a,)).lastrowid
    po = db.execute(
        "INSERT INTO purchase_orders (po_number, partner_id, po_date, company_id) VALUES ('PO-1',?,'2026-10-01',?)",
        (p, a),
    ).lastrowid
    pol = db.execute(
        "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,8,500,4000)",
        (po, it),
    ).lastrowid
    gr = db.execute(
        "INSERT INTO goods_receipts (gr_number, po_id, warehouse_id, receipt_date, company_id) "
        "VALUES ('GR-1',?,?,'2026-10-03',?)", (po, wh, a),
    ).lastrowid
    db.execute(
        "INSERT INTO gr_lines (gr_id, po_line_id, item_id, received_qty) VALUES (?,?,?,8)", (gr, pol, it)
    )
    db.commit()

    html = login("a_mgr").get(f"/goods-receipts/{gr}/print").text
    assert "입 고 증" in html
    assert "입고거래처" in html
    assert "품목C" in html
    assert "4,000" in html


def test_gr_print_blocks_other_company(db, seed, login):
    b = seed["b"]["company"]
    p = _partner(db, b, MARK)
    po = db.execute(
        "INSERT INTO purchase_orders (po_number, partner_id, po_date, company_id) VALUES ('PO-9',?,'2026-10-01',?)",
        (p, b),
    ).lastrowid
    gr = db.execute(
        "INSERT INTO goods_receipts (gr_number, po_id, receipt_date, company_id) VALUES ('GR-9',?,'2026-10-01',?)",
        (po, b),
    ).lastrowid
    db.commit()

    r = login("a_mgr").get(f"/goods-receipts/{gr}/print", follow_redirects=False)
    assert r.status_code == 303
    assert MARK not in r.text
