from tests.conftest import csrf


def _cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_partner_id_schema(db):
    assert "partner_id" in _cols(db, "quotations")
    assert "customer_id" not in _cols(db, "quotations")
    assert "partner_id" in _cols(db, "sales_orders")
    assert "customer_id" not in _cols(db, "sales_orders")


def test_ship_save_route_posts_slip_with_partner(db, seed, login):
    a = seed["a"]["company"]
    partner_id = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('C1','가고객',?,'customer')", (a,)
    ).lastrowid
    item_id = db.execute(
        "INSERT INTO items (item_code, item_name, unit_price) VALUES ('I1','품목1',1000)"
    ).lastrowid
    wh_id = db.execute("INSERT INTO warehouses (code, name) VALUES ('W1','창고1')").lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,100)", (item_id, wh_id))
    so_id = db.execute(
        """INSERT INTO sales_orders (so_number, partner_id, order_date, status, total_amount, tax_amount, created_by)
           VALUES ('SO-2026-0001',?,'2026-09-20','confirmed',10000,1000,?)""",
        (partner_id, seed["a"]["wk"]),
    ).lastrowid
    so_line_id = db.execute(
        "INSERT INTO so_lines (so_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,10,1000,10000)",
        (so_id, item_id),
    ).lastrowid
    db.commit()

    c = login("a_wk")
    tok = csrf(c, f"/shipments/new?so_id={so_id}")
    r = c.post("/shipments/save", data={
        "csrf_token": tok,
        "so_id": str(so_id),
        "warehouse_id": str(wh_id),
        "ship_date": "2026-09-20",
        "line_nums": "1",
        f"so_line_id_1": str(so_line_id),
        "item_id_1": str(item_id),
        "ship_qty_1": "10",
    }, follow_redirects=False)
    assert r.status_code == 303

    doc = db.execute("SELECT * FROM erp_docs WHERE source_type='ship' ORDER BY id DESC LIMIT 1").fetchone()
    assert doc is not None
    assert doc["company_id"] == a
    line = db.execute(
        "SELECT partner_id FROM slip_lines WHERE doc_id=? AND account_code='110'", (doc["id"],)
    ).fetchone()
    assert line["partner_id"] == partner_id


def test_quote_save_rejects_other_book_partner(db, seed, login):
    b = seed["b"]["company"]
    b_partner = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('C1','나고객',?,'customer')", (b,)
    ).lastrowid
    db.commit()

    c = login("a_wk")
    before = db.execute("SELECT COUNT(*) FROM quotations").fetchone()[0]
    tok = csrf(c, "/quotations/new")
    r = c.post("/quotations/save", data={
        "csrf_token": tok,
        "qt_id": "0",
        "partner_id": str(b_partner),
        "quote_date": "2026-09-20",
        "line_nums": "",
    }, follow_redirects=False)
    assert r.status_code == 400
    after = db.execute("SELECT COUNT(*) FROM quotations").fetchone()[0]
    assert after == before


def test_quote_save_requires_partner(db, seed, login):
    c = login("a_wk")
    tok = csrf(c, "/quotations/new")
    r = c.post("/quotations/save", data={
        "csrf_token": tok, "qt_id": "0", "partner_id": "0",
        "quote_date": "2026-09-20", "line_nums": "",
    }, follow_redirects=False)
    assert r.status_code == 400
    assert db.execute("SELECT COUNT(*) FROM quotations").fetchone()[0] == 0


def test_po_save_rejects_other_book_partner(db, seed, login):
    b = seed["b"]["company"]
    b_partner = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('S1','나공급',?,'supplier')", (b,)
    ).lastrowid
    db.commit()
    c = login("a_wk")
    assert "나공급" not in c.get("/purchase-orders/new").text
    tok = csrf(c, "/purchase-orders/new")
    r = c.post("/purchase-orders/save", data={
        "csrf_token": tok, "po_id": "0", "partner_id": str(b_partner),
        "po_date": "2026-09-20", "line_nums": "",
    }, follow_redirects=False)
    assert r.status_code == 400
    assert db.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0] == 0
