import pytest

from core import returns
from tests.test_stock_cost import _base, _gl, _gr, _po, _ship, _so


@pytest.fixture
def setup(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    po, pl = _po(db, a, b, uid, 1000)
    so, sl = _so(db, a, b, uid, qty=10)
    db.commit()
    c = login("a_wk")
    assert _gr(c, po, pl, b, 10).status_code == 303
    assert _ship(c, so, sl, b, 4).status_code == 303
    gr = db.execute("SELECT id FROM goods_receipts WHERE po_id=?", (po,)).fetchone()[0]
    ship = db.execute("SELECT id FROM shipments WHERE so_id=?", (so,)).fetchone()[0]
    grl = db.execute("SELECT id FROM gr_lines WHERE gr_id=?", (gr,)).fetchone()[0]
    shl = db.execute("SELECT id FROM ship_lines WHERE ship_id=?", (ship,)).fetchone()[0]
    return {"a": a, "uid": uid, "b": b, "po": po, "pl": pl, "so": so, "sl": sl, "gr": gr, "ship": ship,
            "grl": grl, "shl": shl, "b_book": seed["b"]["company"]}


def test_gr_return_slip_stock_invoice(db, setup):
    s = setup
    rid = returns.create(db, s["a"], s["uid"], "gr", s["gr"], "2026-09-15", {s["grl"]: 3}, "", "GR-2026-9001")
    assert db.execute("SELECT quantity FROM stock WHERE item_id=?", (s["b"]["item"],)).fetchone()[0] == 3
    assert db.execute("SELECT returned_qty FROM po_lines WHERE id=?", (s["pl"],)).fetchone()[0] == 3
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (s["po"],)).fetchone()[0] == "partial"
    doc = db.execute("SELECT id FROM erp_docs WHERE source_type='gr_return' AND source_id=?", (rid,)).fetchone()[0]
    lines = {r[0]: (r[1], r[2]) for r in db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (doc,))}
    assert lines == {"120": (0, 3000), "135": (0, 300), "251": (3300, 0)}
    inv = db.execute("SELECT supply_amt, vat, status, amend_reason, orig_id FROM tax_invoices WHERE doc_id=?",
                     (doc,)).fetchone()
    assert (inv[0], inv[1], inv[2], inv[3]) == (-3000, -300, "수정", 3) and inv[4]


def test_gr_return_limit_and_shortage(db, setup):
    s = setup
    with pytest.raises(ValueError, match="초과"):
        returns.create(db, s["a"], s["uid"], "gr", s["gr"], "2026-09-15", {s["grl"]: 11}, "", "GR-2026-9001")
    returns.create(db, s["a"], s["uid"], "gr", s["gr"], "2026-09-15", {s["grl"]: 4}, "", "GR-2026-9001")
    assert returns.limits(db, s["a"], "gr", s["gr"]) == {s["grl"]: 6}
    # 출고 4개 후 재고 2개. 반품 가능 6개여도 재고 부족
    with pytest.raises(ValueError, match="재고 부족"):
        returns.create(db, s["a"], s["uid"], "gr", s["gr"], "2026-09-16", {s["grl"]: 5}, "", "GR-2026-9002")


def test_ship_return_cogs_and_revenue(db, setup):
    s = setup
    cogs_before = _gl(db, s["a"], "451")
    rid = returns.create(db, s["a"], s["uid"], "ship", s["ship"], "2026-09-25", {s["shl"]: 2}, "", "SH-2026-9001")
    assert db.execute("SELECT quantity FROM stock WHERE item_id=?", (s["b"]["item"],)).fetchone()[0] == 8
    assert db.execute("SELECT returned_qty FROM so_lines WHERE id=?", (s["sl"],)).fetchone()[0] == 2
    doc = db.execute("SELECT id FROM erp_docs WHERE source_type='ship_return' AND source_id=?", (rid,)).fetchone()[0]
    rows = [tuple(r) for r in db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc,))]
    assert ("110", 0, 4400) in rows and ("401", 4000, 0) in rows and ("255", 400, 0) in rows
    assert ("120", 2000, 0) in rows and ("451", 0, 2000) in rows
    assert _gl(db, s["a"], "451") == cogs_before - 2000


def test_backlog_remain_includes_returns(db, setup, login):
    s = setup
    returns.create(db, s["a"], s["uid"], "gr", s["gr"], "2026-09-15", {s["grl"]: 3}, "", "GR-2026-9001")
    db.commit()
    html = login("a_mgr").get("/purchase-orders/unreceived").text
    assert "PO-2026-0001" in html


def test_cancel_restores(db, setup):
    s = setup
    rid = returns.create(db, s["a"], s["uid"], "ship", s["ship"], "2026-09-25", {s["shl"]: 2}, "", "SH-2026-9001")
    returns.cancel(db, s["a"], s["uid"], "ship", rid)
    assert db.execute("SELECT quantity FROM stock WHERE item_id=?", (s["b"]["item"],)).fetchone()[0] == 6
    assert db.execute("SELECT returned_qty FROM so_lines WHERE id=?", (s["sl"],)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM tax_invoices WHERE source_type='amend'").fetchone()[0] == 0
    assert _gl(db, s["a"], "110") == 8800
    with pytest.raises(ValueError, match="이미"):
        returns.cancel(db, s["a"], s["uid"], "ship", rid)
    assert returns.limits(db, s["a"], "ship", s["ship"]) == {s["shl"]: 4}


def test_gr_cancel_restores_cost(db, setup):
    s = setup
    amt = db.execute("SELECT stock_amt FROM items WHERE id=?", (s["b"]["item"],)).fetchone()[0]
    rid = returns.create(db, s["a"], s["uid"], "gr", s["gr"], "2026-09-15", {s["grl"]: 3}, "", "GR-2026-9001")
    returns.cancel(db, s["a"], s["uid"], "gr", rid)
    assert db.execute("SELECT stock_amt FROM items WHERE id=?", (s["b"]["item"],)).fetchone()[0] == amt
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (s["po"],)).fetchone()[0] == "completed"


def test_other_company_not_found(db, setup):
    s = setup
    with pytest.raises(LookupError):
        returns.create(db, s["b_book"], s["uid"], "gr", s["gr"], "2026-09-15", {s["grl"]: 1}, "", "GR-2026-9001")
