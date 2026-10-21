import pytest

from tests.conftest import csrf
from tests.test_stock_cost import _base, _po


def _gr_qc(c, po, line, b, qty, qc=True, defect=0):
    return c.post("/goods-receipts/save", data={
        "csrf_token": csrf(c, f"/goods-receipts/new?po_id={po}"), "po_id": str(po), "warehouse_id": str(b["wh"]),
        "receipt_date": "2026-09-10", "line_nums": "1", "po_line_id_1": str(line), "item_id_1": str(b["item"]),
        "recv_qty_1": str(qty), "defect_qty_1": str(defect),
        **({"qc_required": "1"} if qc else {}),
    }, follow_redirects=False)


def _inspect(c, gr_id, results, memo=""):
    data = {"csrf_token": csrf(c, f"/goods-receipts/{gr_id}"), "inspect_memo": memo}
    for lid, (p, f) in results.items():
        data[f"pass_qty_{lid}"] = str(p)
        data[f"fail_qty_{lid}"] = str(f)
    return c.post(f"/goods-receipts/{gr_id}/inspection", data=data, follow_redirects=False)


@pytest.fixture
def setup(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    po, pl = _po(db, a, b, uid, 1000)
    db.commit()
    c = login("a_wk")
    r = _gr_qc(c, po, pl, b, 10, qc=True)
    assert r.status_code == 303
    gr = int(r.headers["location"].rsplit("/", 1)[-1])
    grl = db.execute("SELECT id FROM gr_lines WHERE gr_id=?", (gr,)).fetchone()[0]
    return {"a": a, "uid": uid, "b": b, "po": po, "pl": pl, "gr": gr, "grl": grl}


def test_qc_pending_on_save(db, setup):
    s = setup
    assert db.execute("SELECT qc_status FROM goods_receipts WHERE id=?", (s["gr"],)).fetchone()[0] == "pending"


def test_no_qc_leaves_status_blank(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    po, pl = _po(db, a, b, uid, 1000, no="0002")
    db.commit()
    c = login("a_wk")
    r = _gr_qc(c, po, pl, b, 10, qc=False)
    gr = int(r.headers["location"].rsplit("/", 1)[-1])
    assert db.execute("SELECT qc_status FROM goods_receipts WHERE id=?", (gr,)).fetchone()[0] == ""


def test_qc_detail_shows_inspect_form(db, setup, login):
    s = setup
    html = login("a_wk").get(f"/goods-receipts/{s['gr']}").text
    assert "검사대기" in html and "검사 결과 입력" in html


def test_inspect_all_pass(db, setup, login):
    s = setup
    c = login("a_wk")
    r = _inspect(c, s["gr"], {s["grl"]: (10, 0)})
    assert r.status_code == 303
    assert db.execute("SELECT qc_status FROM goods_receipts WHERE id=?", (s["gr"],)).fetchone()[0] == "passed"
    html = c.get(f"/goods-receipts/{s['gr']}").text
    assert "합격" in html


def test_inspect_with_failure(db, setup, login):
    s = setup
    c = login("a_wk")
    r = _inspect(c, s["gr"], {s["grl"]: (7, 3)}, memo="표면 스크래치")
    assert r.status_code == 303
    assert db.execute("SELECT qc_status FROM goods_receipts WHERE id=?", (s["gr"],)).fetchone()[0] == "failed"
    html = c.get(f"/goods-receipts/{s['gr']}").text
    assert "불합격" in html and "표면 스크래치" in html
    assert f"qty_{s['grl']}=3" in html


def test_inspect_qty_mismatch_rejected(db, setup, login):
    s = setup
    c = login("a_wk")
    r = _inspect(c, s["gr"], {s["grl"]: (7, 1)})
    assert r.status_code == 400
    assert db.execute("SELECT qc_status FROM goods_receipts WHERE id=?", (s["gr"],)).fetchone()[0] == "pending"


def test_inspect_not_pending_rejected(db, setup, login):
    s = setup
    c = login("a_wk")
    assert _inspect(c, s["gr"], {s["grl"]: (10, 0)}).status_code == 303
    r = _inspect(c, s["gr"], {s["grl"]: (10, 0)})
    assert r.status_code == 400


def test_inspect_other_company_404(db, setup, login):
    s = setup
    c = login("b_mgr")
    r = c.post(f"/goods-receipts/{s['gr']}/inspection", data={
        "csrf_token": csrf(c, f"/goods-receipts/{s['gr']}"),
        f"pass_qty_{s['grl']}": "10", f"fail_qty_{s['grl']}": "0",
    })
    assert r.status_code == 404


def test_return_form_prefill_from_fail_qty(db, setup, login):
    s = setup
    c = login("a_wk")
    _inspect(c, s["gr"], {s["grl"]: (7, 3)})
    html = c.get(f"/goods-receipts/{s['gr']}/return?qty_{s['grl']}=3").text
    assert 'value="3"' in html


def test_return_form_prefill_capped(db, setup, login):
    s = setup
    c = login("a_wk")
    _inspect(c, s["gr"], {s["grl"]: (7, 3)})
    # 쿼리로 넘어온 수량이 반품 가능 한도(returns.limits, 양품수량 10)를 넘으면 한도로 캡
    html = c.get(f"/goods-receipts/{s['gr']}/return?qty_{s['grl']}=999").text
    assert 'value="10"' in html
