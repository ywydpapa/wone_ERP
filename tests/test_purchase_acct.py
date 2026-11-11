import json

import pytest

from core import returns
from tests.conftest import csrf
from tests.test_stock_cost import _base


def _nonstock_item(db, cid, code, acct="821"):
    return db.execute(
        "INSERT INTO items (item_code, item_name, unit_price, company_id, is_stock, account_code) "
        "VALUES (?,'용역',5000,?,0,?)", (f"N{code}", cid, acct)
    ).lastrowid


def _po_line(db, cid, b, uid, item, price, qty=1, acct="", no="0001"):
    po = db.execute(
        """INSERT INTO purchase_orders (po_number, partner_id, po_date, status, total_amount, tax_amount, created_by, company_id)
           VALUES (?,?,'2026-09-01','confirmed',?,0,?,?)""",
        (f"PO-2026-{no}", b["sup"], price * qty, uid, cid),
    ).lastrowid
    line = db.execute(
        "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount, account_code) VALUES (?,1,?,?,?,?,?)",
        (po, item, qty, price, price * qty, acct),
    ).lastrowid
    return po, line


def _gr_multi(c, po, b, lines, date="2026-09-10"):
    nums = [str(i) for i in range(1, len(lines) + 1)]
    data = {"csrf_token": csrf(c, f"/goods-receipts/new?po_id={po}"), "po_id": str(po),
            "warehouse_id": str(b["wh"]), "receipt_date": date, "line_nums": ",".join(nums)}
    for i, (po_line_id, item_id, qty, defect) in enumerate(lines, 1):
        data[f"po_line_id_{i}"] = str(po_line_id)
        data[f"item_id_{i}"] = str(item_id)
        data[f"recv_qty_{i}"] = str(qty)
        data[f"defect_qty_{i}"] = str(defect)
    return c.post("/goods-receipts/save", data=data, follow_redirects=False)


@pytest.fixture
def ctx(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    b = _base(db, a)
    return a, uid, b


def test_nonstock_gr_slip(db, ctx, login):
    a, uid, b = ctx
    item = _nonstock_item(db, a, "1")
    po, line = _po_line(db, a, b, uid, item, 5000, acct="821")
    db.commit()
    c = login("a_wk")
    r = _gr_multi(c, po, b, [(line, item, 1, 0)])
    assert r.status_code == 303
    gr = int(r.headers["location"].rsplit("/", 1)[-1])

    assert db.execute("SELECT COUNT(*) FROM stock WHERE item_id=?", (item,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM stock_transactions WHERE item_id=?", (item,)).fetchone()[0] == 0

    doc = db.execute("SELECT id FROM erp_docs WHERE source_type='gr' AND source_id=?", (gr,)).fetchone()[0]
    lines = {r2[0]: (r2[1], r2[2]) for r2 in db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (doc,))}
    assert lines == {"821": (5000, 0), "135": (500, 0), "251": (0, 5500)}


def test_mixed_po_gr_slip_split(db, ctx, login):
    a, uid, b = ctx
    nitem = _nonstock_item(db, a, "2")
    po = db.execute(
        """INSERT INTO purchase_orders (po_number, partner_id, po_date, status, total_amount, tax_amount, created_by, company_id)
           VALUES ('PO-2026-0002',?,'2026-09-01','confirmed',0,0,?,?)""", (b["sup"], uid, a)
    ).lastrowid
    l1 = db.execute(
        "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,10,1000,10000)",
        (po, b["item"]),
    ).lastrowid
    l2 = db.execute(
        "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount, account_code) VALUES (?,2,?,1,5000,5000,'821')",
        (po, nitem),
    ).lastrowid
    db.commit()
    c = login("a_wk")
    r = _gr_multi(c, po, b, [(l1, b["item"], 10, 0), (l2, nitem, 1, 0)])
    assert r.status_code == 303
    gr = int(r.headers["location"].rsplit("/", 1)[-1])

    assert db.execute("SELECT quantity FROM stock WHERE item_id=?", (b["item"],)).fetchone()[0] == 10
    assert db.execute("SELECT COUNT(*) FROM stock WHERE item_id=?", (nitem,)).fetchone()[0] == 0

    doc = db.execute("SELECT id FROM erp_docs WHERE source_type='gr' AND source_id=?", (gr,)).fetchone()[0]
    rows = {r2[0]: (r2[1], r2[2]) for r2 in db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (doc,))}
    # 차변만 재고 120, 비재고 821로 분리. 대변은 251 단일 기준
    assert rows == {"120": (10000, 0), "821": (5000, 0), "135": (1500, 0), "251": (0, 16500)}
    s = db.execute("SELECT SUM(debit), SUM(credit) FROM slip_lines WHERE doc_id=?", (doc,)).fetchone()
    assert s[0] == s[1]


def test_pr_po_acct_carry(db, ctx, login):
    a, uid, b = ctx
    db.execute("INSERT INTO depts (company_id, code, name) VALUES (?,'D1','총무팀')", (a,))
    nitem = _nonstock_item(db, a, "3")
    pr = db.execute(
        """INSERT INTO purchase_requisitions (pr_number, requester_id, dept, request_date, status, company_id)
           VALUES ('PR-2026-0001', ?, '총무팀', '2026-09-01', 'approved', ?)""", (uid, a)
    ).lastrowid
    db.execute(
        """INSERT INTO pr_lines (pr_id, line_no, item_id, item_name, quantity, estimated_price, account_code, dept, project_code)
           VALUES (?,1,?,'용역',1,5000,'821','총무팀','PJ-01')""", (pr, nitem),
    )
    db.commit()
    c = login("a_wk")
    tok = csrf(c, "/purchase-requisitions")
    r = c.post(f"/purchase-requisitions/{pr}/convert", data={"csrf_token": tok}, follow_redirects=False)
    assert r.status_code == 303
    po_id = int(r.headers["location"].rsplit("/", 1)[-1])
    row = db.execute("SELECT account_code, dept, project_code FROM po_lines WHERE po_id=?", (po_id,)).fetchone()
    assert tuple(row) == ("821", "총무팀", "PJ-01")


def test_nonstock_return(db, ctx, login):
    a, uid, b = ctx
    nitem = _nonstock_item(db, a, "4")
    po, line = _po_line(db, a, b, uid, nitem, 5000, acct="821", no="0004")
    db.commit()
    c = login("a_wk")
    r = _gr_multi(c, po, b, [(line, nitem, 1, 0)])
    gr = int(r.headers["location"].rsplit("/", 1)[-1])
    grl = db.execute("SELECT id FROM gr_lines WHERE gr_id=?", (gr,)).fetchone()[0]

    rid = returns.create(db, a, uid, "gr", gr, "2026-09-15", {grl: 1}, "", "GR-2026-9001")
    assert db.execute("SELECT COUNT(*) FROM stock WHERE item_id=?", (nitem,)).fetchone()[0] == 0

    doc = db.execute("SELECT id FROM erp_docs WHERE source_type='gr_return' AND source_id=?", (rid,)).fetchone()[0]
    lines = {r2[0]: (r2[1], r2[2]) for r2 in db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=?", (doc,))}
    assert lines == {"821": (0, 5000), "135": (0, 500), "251": (5500, 0)}


def test_pay_blocked_stop(db, seed, login):
    a = seed["a"]["company"]
    pid = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type, trade_status) VALUES ('S9','중지거래처',?,'supplier','stop')",
        (a,),
    ).lastrowid
    db.commit()
    c = login("a_wk")
    tok = csrf(c, "/settlements/new")
    r = c.post("/settlements", data={
        "csrf_token": tok, "kind": "지급", "settle_date": "2026-10-10", "partner_id": str(pid),
        "amount": "1000", "method": "현금", "wht_type": "없음", "memo": "",
    })
    assert r.status_code == 400
    assert "거래중지" in r.json()["notice"]
    assert db.execute("SELECT COUNT(*) FROM settlements").fetchone()[0] == 0


def _text_pr(db, a, uid):
    pr = db.execute(
        """INSERT INTO purchase_requisitions (pr_number, requester_id, request_date, status, company_id)
           VALUES ('PR-2026-0009', ?, '2026-09-01', 'approved', ?)""", (uid, a)
    ).lastrowid
    db.execute("INSERT INTO pr_lines (pr_id, line_no, item_name, quantity, estimated_price) VALUES (?,1,'볼트',3,1000)", (pr,))
    db.commit()
    return pr


def _po_post(c, b, pr_id=0, item="", text=""):
    data = {"csrf_token": csrf(c, "/purchase-orders/new"), "po_id": "0", "pr_id": str(pr_id),
            "partner_id": str(b["sup"]), "po_date": "2026-09-02", "line_nums": "1",
            "item_id_1": str(item), "item_text_1": text, "qty_1": "3", "price_1": "1000"}
    return c.post("/purchase-orders/save", data=data, follow_redirects=False)


def test_po_no_item(db, ctx, login):
    a, uid, b = ctx
    db.commit()
    c = login("a_wk")
    r = _po_post(c, b, text="볼트")
    assert r.status_code == 400
    assert "1번째 줄" in r.json()["error"]
    assert _po_post(c, b).status_code == 400
    assert db.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0] == 0


def test_pr_text_to_po_form(db, ctx, login):
    a, uid, b = ctx
    pr = _text_pr(db, a, uid)
    c = login("a_wk")
    r = c.post(f"/purchase-requisitions/{pr}/convert", data={"csrf_token": csrf(c, "/purchase-requisitions")},
               follow_redirects=False)
    assert r.headers["location"] == f"/purchase-orders/new?pr_id={pr}"
    html = c.get(r.headers["location"]).text
    assert f'name="pr_id" value="{pr}"' in html
    assert json.dumps("볼트") in html


def test_po_from_pr(db, ctx, login):
    a, uid, b = ctx
    pr = _text_pr(db, a, uid)
    c = login("a_wk")
    assert _po_post(c, b, pr_id=pr, item=b["item"]).status_code == 303
    assert db.execute("SELECT status FROM purchase_requisitions WHERE id=?", (pr,)).fetchone()[0] == "converted"
    assert _po_post(c, b, pr_id=pr, item=b["item"]).status_code == 400
