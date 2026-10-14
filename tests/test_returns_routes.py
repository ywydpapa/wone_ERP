import pytest

from tests.conftest import csrf
from tests.test_stock_cost import _base, _gr, _ship, _so, _po


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
    return {"a": a, "uid": uid, "b": b, "po": po, "pl": pl, "so": so, "sl": sl,
            "gr": gr, "ship": ship, "grl": grl, "shl": shl}


def _ret(c, typ, doc_id, qtys, ret_date="2026-09-15"):
    base = "/goods-receipts" if typ == "gr" else "/shipments"
    data = {"csrf_token": csrf(c, f"{base}/{doc_id}/return"), "ret_date": ret_date, "notes": ""}
    data.update({f"qty_{lid}": str(q) for lid, q in qtys.items()})
    return c.post(f"{base}/{doc_id}/return", data=data, follow_redirects=False)


def test_gr_return_post_and_detail(db, setup, login):
    s = setup
    c = login("a_wk")
    r = _ret(c, "gr", s["gr"], {s["grl"]: 3})
    assert r.status_code == 303
    ret_id = int(r.headers["location"].rsplit("/", 1)[-1])

    ret_html = c.get(f"/goods-receipts/{ret_id}").text
    assert "반품" in ret_html and f"/goods-receipts/{s['gr']}" in ret_html

    orig_html = c.get(f"/goods-receipts/{s['gr']}").text
    assert "반품" in orig_html

    # 발주 수량 10 전량입고 후 완료 상태였으나 반품으로 다시 미입고 현황에 노출
    assert "PO-2026-0001" in login("a_mgr").get("/purchase-orders/unreceived").text


def test_gr_return_over_limit(db, setup, login):
    s = setup
    c = login("a_wk")
    r = _ret(c, "gr", s["gr"], {s["grl"]: 11})
    assert r.status_code == 400 and "초과" in r.json()["error"]


def test_gr_return_stock_shortage(db, setup, login):
    s = setup
    c = login("a_wk")
    assert _ret(c, "gr", s["gr"], {s["grl"]: 4}).status_code == 303
    # 반품 4개 후 재고 2개. 반품 가능 수량은 6개여도 재고 부족으로 거절
    r = _ret(c, "gr", s["gr"], {s["grl"]: 5}, ret_date="2026-09-16")
    assert r.status_code == 400 and "재고 부족" in r.json()["error"]


def test_gr_return_form_other_company_404(db, setup, login):
    s = setup
    r = login("b_mgr").get(f"/goods-receipts/{s['gr']}/return")
    assert r.status_code == 404


def test_gr_return_cancel_requires_editor(db, setup, login):
    s = setup
    c = login("a_wk")
    r = _ret(c, "gr", s["gr"], {s["grl"]: 3})
    ret_id = int(r.headers["location"].rsplit("/", 1)[-1])

    deny = c.request("DELETE", f"/goods-receipts/{ret_id}", data={"csrf_token": csrf(c, f"/goods-receipts/{ret_id}")})
    assert deny.status_code == 403

    mgr = login("a_mgr")
    ok = mgr.request("DELETE", f"/goods-receipts/{ret_id}",
                     data={"csrf_token": csrf(mgr, f"/goods-receipts/{ret_id}")})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert db.execute("SELECT canceled_at FROM goods_receipts WHERE id=?", (ret_id,)).fetchone()[0]


def test_gr_return_allows_rereceive(db, setup, login):
    s = setup
    c = login("a_wk")
    assert _ret(c, "gr", s["gr"], {s["grl"]: 3}).status_code == 303
    # 반품 3개로 과입고 검사 기준이 다시 열려 추가 입고 가능
    r = _gr(c, s["po"], s["pl"], s["b"], 3)
    assert r.status_code == 303 and "error=" not in r.headers["location"]


def test_gr_return_cancel_restores_backlog(db, setup, login):
    s = setup
    c = login("a_wk")
    r = _ret(c, "gr", s["gr"], {s["grl"]: 3})
    ret_id = int(r.headers["location"].rsplit("/", 1)[-1])
    mgr = login("a_mgr")
    mgr.request("DELETE", f"/goods-receipts/{ret_id}", data={"csrf_token": csrf(mgr, f"/goods-receipts/{ret_id}")})
    assert "취소됨" in mgr.get(f"/goods-receipts/{ret_id}").text
    assert "PO-2026-0001" not in mgr.get("/purchase-orders/unreceived").text


def test_ship_return_post_and_detail(db, setup, login):
    s = setup
    c = login("a_wk")
    r = _ret(c, "ship", s["ship"], {s["shl"]: 2}, ret_date="2026-09-25")
    assert r.status_code == 303
    ret_id = int(r.headers["location"].rsplit("/", 1)[-1])
    ret_html = c.get(f"/shipments/{ret_id}").text
    assert "반품" in ret_html and f"/shipments/{s['ship']}" in ret_html
    orig_html = c.get(f"/shipments/{s['ship']}").text
    assert "반품" in orig_html


def test_ship_return_reopens_unshipped(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,20)", (b["item"], b["wh"]))
    so, sl = _so(db, a, b, uid, qty=10)
    db.commit()
    c = login("a_wk")
    assert _ship(c, so, sl, b, 10).status_code == 303
    assert "SO-2026-0001" not in login("a_mgr").get("/sales-orders/unshipped").text

    ship = db.execute("SELECT id FROM shipments WHERE so_id=?", (so,)).fetchone()[0]
    shl = db.execute("SELECT id FROM ship_lines WHERE ship_id=?", (ship,)).fetchone()[0]
    r = _ret(c, "ship", ship, {shl: 2}, ret_date="2026-09-25")
    assert r.status_code == 303
    assert "SO-2026-0001" in login("a_mgr").get("/sales-orders/unshipped").text


def test_ship_return_form_other_company_404(db, setup, login):
    s = setup
    r = login("b_mgr").get(f"/shipments/{s['ship']}/return")
    assert r.status_code == 404
