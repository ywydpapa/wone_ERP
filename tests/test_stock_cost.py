import pytest

from tests.conftest import csrf
from core import stock


def _base(db, cid, code="1"):
    sup = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES (?,?,?,'supplier')",
        (f"S{code}", f"공급{code}", cid),
    ).lastrowid
    cus = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES (?,?,?,'customer')",
        (f"C{code}", f"고객{code}", cid),
    ).lastrowid
    item = db.execute(
        "INSERT INTO items (item_code, item_name, unit_price, company_id) VALUES (?,'품목',2000,?)", (f"I{code}", cid)
    ).lastrowid
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES (?,'창고',?)", (f"W{code}", cid)).lastrowid
    return {"sup": sup, "cus": cus, "item": item, "wh": wh}


def _po(db, cid, b, uid, price, qty=10, no="0001"):
    po = db.execute(
        """INSERT INTO purchase_orders (po_number, partner_id, po_date, status, total_amount, tax_amount, created_by, company_id)
           VALUES (?,?,'2026-09-01','confirmed',?,0,?,?)""",
        (f"PO-2026-{no}", b["sup"], price * qty, uid, cid),
    ).lastrowid
    line = db.execute(
        "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,?,?,?)",
        (po, b["item"], qty, price, price * qty),
    ).lastrowid
    return po, line


def _so(db, cid, b, uid, qty=10, no="0001"):
    so = db.execute(
        """INSERT INTO sales_orders (so_number, partner_id, order_date, status, total_amount, tax_amount, created_by, company_id)
           VALUES (?,?,'2026-09-01','confirmed',0,0,?,?)""",
        (f"SO-2026-{no}", b["cus"], uid, cid),
    ).lastrowid
    line = db.execute(
        "INSERT INTO so_lines (so_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,?,2000,?)",
        (so, b["item"], qty, qty * 2000),
    ).lastrowid
    return so, line


def _gr(c, po, line, b, qty, defect=0):
    return c.post("/goods-receipts/save", data={
        "csrf_token": csrf(c, f"/goods-receipts/new?po_id={po}"), "po_id": str(po), "warehouse_id": str(b["wh"]),
        "receipt_date": "2026-09-10", "line_nums": "1", "po_line_id_1": str(line), "item_id_1": str(b["item"]),
        "recv_qty_1": str(qty), "defect_qty_1": str(defect),
    }, follow_redirects=False)


def _ship(c, so, line, b, qty):
    return c.post("/shipments/save", data={
        "csrf_token": csrf(c, f"/shipments/new?so_id={so}"), "so_id": str(so), "warehouse_id": str(b["wh"]),
        "ship_date": "2026-09-20", "line_nums": "1", "so_line_id_1": str(line), "item_id_1": str(b["item"]),
        "ship_qty_1": str(qty),
    }, follow_redirects=False)


def _gl(db, cid, code):
    return db.execute(
        """SELECT COALESCE(SUM(sl.debit - sl.credit), 0) FROM slip_lines sl JOIN erp_docs d ON d.id=sl.doc_id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code=?""",
        (cid, code),
    ).fetchone()[0]


def test_moving_average_cogs(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    po1, l1 = _po(db, a, b, uid, 1000)
    po2, l2 = _po(db, a, b, uid, 1300, no="0002")
    so, sl = _so(db, a, b, uid, qty=20)
    db.commit()
    c = login("a_wk")
    assert _gr(c, po1, l1, b, 10).status_code == 303
    assert _gr(c, po2, l2, b, 10).status_code == 303
    assert db.execute("SELECT stock_amt FROM items WHERE id=?", (b["item"],)).fetchone()[0] == 23000

    assert _ship(c, so, sl, b, 5).status_code == 303
    assert _gl(db, a, "451") == 5750
    assert _gl(db, a, "120") == 23000 - 5750
    doc = db.execute("SELECT id FROM erp_docs WHERE source_type='ship'").fetchone()[0]
    s = db.execute("SELECT SUM(debit), SUM(credit) FROM slip_lines WHERE doc_id=?", (doc,)).fetchone()
    assert s[0] == s[1]

    # 전량 출고 시 잔액 0, 단수차이 없음
    assert _ship(c, so, sl, b, 15).status_code == 303
    assert db.execute("SELECT stock_amt FROM items WHERE id=?", (b["item"],)).fetchone()[0] == 0
    assert _gl(db, a, "120") == 0
    assert _gl(db, a, "451") == 23000

    r = c.get("/stock/valuation?date_to=2026-09-15")
    assert r.status_code == 200 and "23,000" in r.text


def test_defect_excluded_from_cost(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    po, line = _po(db, a, b, uid, 1000)
    db.commit()
    c = login("a_wk")
    assert _gr(c, po, line, b, 10, defect=2).status_code == 303
    assert db.execute("SELECT stock_amt FROM items WHERE id=?", (b["item"],)).fetchone()[0] == 8000
    assert _gl(db, a, "120") == 8000


def test_ship_over_so_remain(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,100)", (b["item"], b["wh"]))
    so, sl = _so(db, a, b, uid, qty=10)
    db.commit()
    c = login("a_wk")
    r = _ship(c, so, sl, b, 11)
    assert r.status_code == 400 and "수주 잔량 초과" in r.json()["error"]
    assert db.execute("SELECT quantity FROM stock WHERE item_id=?", (b["item"],)).fetchone()[0] == 100


def test_foreign_so_line_ignored(db, seed, login):
    a, bc = seed["a"]["company"], seed["b"]["company"]
    ba = _base(db, a)
    bb = _base(db, bc, "2")
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,100)", (ba["item"], ba["wh"]))
    so_a, _ = _so(db, a, ba, seed["a"]["wk"])
    _, sl_b = _so(db, bc, bb, seed["b"]["wk"], no="0002")
    db.commit()
    c = login("a_wk")
    r = _ship(c, so_a, sl_b, ba, 3)
    assert r.status_code == 400
    assert db.execute("SELECT shipped_qty FROM so_lines WHERE id=?", (sl_b,)).fetchone()[0] == 0


def test_foreign_po_line_ignored(db, seed, login):
    a, bc = seed["a"]["company"], seed["b"]["company"]
    ba = _base(db, a)
    bb = _base(db, bc, "2")
    po_a, _ = _po(db, a, ba, seed["a"]["wk"], 1000)
    _, pl_b = _po(db, bc, bb, seed["b"]["wk"], 1000, no="0002")
    db.commit()
    c = login("a_wk")
    _gr(c, po_a, pl_b, ba, 5)
    assert db.execute("SELECT received_qty FROM po_lines WHERE id=?", (pl_b,)).fetchone()[0] == 0


def test_over_receipt_message(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    po, line = _po(db, a, b, uid, 1000)
    db.commit()
    c = login("a_wk")
    r = _gr(c, po, line, b, 12)
    assert r.status_code == 303 and "error=" in r.headers["location"]


def test_move_out_never_negative(db, seed):
    a = seed["a"]["company"]
    b = _base(db, a)
    stock.move_in(db, b["item"], b["wh"], 3, "2026-09-01", "gr", 1, seed["a"]["wk"], 1000)
    with pytest.raises(ValueError, match="재고 부족"):
        stock.move_out(db, b["item"], b["wh"], 4, "2026-09-02", "ship", 1, seed["a"]["wk"])
    assert db.execute("SELECT quantity FROM stock WHERE item_id=?", (b["item"],)).fetchone()[0] == 3


def test_year_end_defaults_to_valuation(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    po, line = _po(db, a, b, uid, 1000)
    so, sl = _so(db, a, b, uid)
    db.commit()
    c = login("a_wk")
    _gr(c, po, line, b, 10)
    _ship(c, so, sl, b, 4)
    c = login("a_mgr")
    r = c.get("/fi/year-end?year=2026")
    assert r.status_code == 200
    assert 'value="6000"' in r.text


def test_backlog_and_links(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    po, line = _po(db, a, b, uid, 1000)
    so, sl = _so(db, a, b, uid)
    _base(db, seed["b"]["company"], "9")
    db.commit()
    c = login("a_wk")
    _gr(c, po, line, b, 4)
    _ship(c, so, sl, b, 3)
    r = c.get("/purchase-orders/unreceived")
    assert r.status_code == 200 and "PO-2026-0001" in r.text and "6,000" in r.text
    r = c.get("/sales-orders/unshipped")
    assert r.status_code == 200 and "SO-2026-0001" in r.text and "14,000" in r.text
    assert "data-pop=\"slip\"" in c.get(f"/purchase-orders/{po}").text
    assert "/tax-invoices/" in c.get(f"/sales-orders/{so}").text
    c = login("b_wk")
    assert "PO-2026-0001" not in c.get("/purchase-orders/unreceived").text
    assert "SO-2026-0001" not in c.get("/sales-orders/unshipped").text


def test_expired_quote(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    qt = db.execute(
        """INSERT INTO quotations (quote_number, partner_id, quote_date, valid_until, status, total_amount, tax_amount, created_by, company_id)
           VALUES ('QT-2026-0001',?,'2026-01-01','2026-01-31','sent',0,0,?,?)""",
        (b["cus"], uid, a),
    ).lastrowid
    db.commit()
    c = login("a_wk")
    tok = csrf(c, "/quotations")
    db.execute("UPDATE quotations SET status='sent' WHERE id=?", (qt,))
    db.commit()
    r = c.post(f"/quotations/{qt}/accept", data={"csrf_token": tok}, follow_redirects=False)
    assert r.status_code == 400
    assert c.get(f"/quotations/{qt}").status_code == 200
    assert db.execute("SELECT status FROM quotations WHERE id=?", (qt,)).fetchone()[0] == "expired"


def test_result_rejects_foreign_worker(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    base = _base(db, a)
    item, w1 = base["item"], base["wh"]
    emp_b = db.execute("SELECT id FROM employees WHERE company_id=?", (b,)).fetchone()[0]
    wo = db.execute(
        """INSERT INTO work_orders (wo_number, product_id, planned_qty, status, created_by, company_id)
           VALUES ('WO-2026-0001',?,10,'released',?,?)""",
        (item, seed["a"]["wk"], a),
    ).lastrowid
    db.commit()
    c = login("a_wk")
    r = c.post("/production-results/save", data={
        "csrf_token": csrf(c, f"/production-results/new?wo_id={wo}"), "wo_id": str(wo), "good_qty": "2",
        "warehouse_id": str(w1), "worker_id": str(emp_b), "result_date": "2026-09-10",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT worker_id FROM production_results WHERE wo_id=?", (wo,)).fetchone()[0] is None
    assert db.execute("SELECT quantity FROM stock WHERE item_id=?", (item,)).fetchone()[0] == 2


def test_valuation_tenant(db, seed, login):
    base = _base(db, seed["b"]["company"], "2")
    item_b, wb = base["item"], base["wh"]
    stock.move_in(db, item_b, wb, 3, "2026-09-01", "gr", 1, seed["b"]["wk"], 7777)
    db.commit()
    c = login("a_mgr")
    assert "23,331" not in c.get("/stock/valuation").text
    c = login("b_mgr")
    assert "23,331" in c.get("/stock/valuation").text
