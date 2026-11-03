from core import books, invoices
from tests.conftest import make_partner


def _partner(db, book, code="S1", biz_no=""):
    return make_partner(db, book, code, partner_type="supplier", biz_no=biz_no)


def test_nondeduct_reason_required(db, seed, login):
    a = seed["a"]["company"]
    pid = _partner(db, a)
    db.commit()
    c = login("a_mgr")
    r = c.post("/tax-invoices", data={
        "kind": "매입", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-10-08",
        "partner_id": str(pid), "acct": "812", "pay": "251", "deduct": "0",
        "line_count": "1", "item_name_1": "품목", "item_qty_1": "1", "item_price_1": "100000",
        "item_supply_1": "100000", "item_vat_1": "10000",
    })
    assert r.status_code == 400
    assert "불공제 사유" in r.json()["error"]


def test_nondeduct_reason_saved(db, seed, login):
    a = seed["a"]["company"]
    pid = _partner(db, a)
    db.commit()
    c = login("a_mgr")
    r = c.post("/tax-invoices", data={
        "kind": "매입", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-10-08",
        "partner_id": str(pid), "acct": "812", "pay": "251", "deduct": "0", "nondeduct_reason": "4",
        "line_count": "1", "item_name_1": "품목", "item_qty_1": "1", "item_price_1": "100000",
        "item_supply_1": "100000", "item_vat_1": "10000",
    }, follow_redirects=False)
    assert r.status_code == 303
    inv = db.execute("SELECT nondeduct_reason FROM tax_invoices WHERE partner_id=?", (pid,)).fetchone()
    assert inv["nondeduct_reason"] == 4

    r2 = c.post("/tax-invoices", data={
        "kind": "매입", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-10-08",
        "partner_id": str(pid), "acct": "812", "pay": "251", "deduct": "0", "nondeduct_reason": "99",
        "line_count": "1", "item_name_1": "품목", "item_qty_1": "1", "item_price_1": "100000",
        "item_supply_1": "100000", "item_vat_1": "10000",
    })
    assert r2.status_code == 400


def test_nondeduct_summary(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = _partner(db, a)
    doc = books.post(
        db, a, uid, "2026-10-01", [{"code": "812", "debit": 11000, "credit": 0, "partner_id": pid, "summary": "x"},
                                    {"code": "251", "debit": 0, "credit": 11000, "partner_id": pid, "summary": "x"}],
        "접대비", "tax", None,
    )
    invoices.add(db, a, uid, {
        "kind": "매입", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-10-01",
        "partner_id": pid, "supply_amt": 10000, "vat": 1000, "doc_id": doc, "deduct": 0, "nondeduct_reason": 4,
    }, [{"name": "접대", "supply_amt": 10000, "vat": 1000}])
    doc2 = books.post(
        db, a, uid, "2026-10-02", [{"code": "812", "debit": 2200, "credit": 0, "partner_id": pid, "summary": "y"},
                                    {"code": "251", "debit": 0, "credit": 2200, "partner_id": pid, "summary": "y"}],
        "불공제미지정", "tax", None,
    )
    invoices.add(db, a, uid, {
        "kind": "매입", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-10-02",
        "partner_id": pid, "supply_amt": 2000, "vat": 200, "doc_id": doc2, "deduct": 0,
    }, [{"name": "미지정", "supply_amt": 2000, "vat": 200}])
    db.commit()

    r = invoices.nondeduct_summary(db, a, "2026-10-01", "2026-10-31")
    by_code = {i[0]: i for i in r["rows"]}
    assert by_code[4][2:] == (1, 10000, 1000)
    assert by_code[1][2:] == (0, 0, 0)
    assert r["unspec"] == (1, 2000, 200)
    assert r["total"] == {"cnt": 2, "supply": 12000, "vat": 1200}


def test_nondeduct_report_route_renders(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = _partner(db, a)
    doc = books.post(
        db, a, uid, "2026-10-01", [{"code": "812", "debit": 11000, "credit": 0, "partner_id": pid, "summary": "x"},
                                    {"code": "251", "debit": 0, "credit": 11000, "partner_id": pid, "summary": "x"}],
        "접대비", "tax", None,
    )
    invoices.add(db, a, uid, {
        "kind": "매입", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-10-01",
        "partner_id": pid, "supply_amt": 10000, "vat": 1000, "doc_id": doc, "deduct": 0, "nondeduct_reason": 4,
    }, [{"name": "접대", "supply_amt": 10000, "vat": 1000}])
    db.commit()

    c = login("a_mgr")
    r = c.get("/tax/nondeduct", params={"date_from": "2026-10-01", "date_to": "2026-10-31"})
    assert r.status_code == 200
    assert "접대비 및 이와 유사한 비용 관련" in r.text and "사유 미지정" in r.text

    r2 = c.get("/tax/nondeduct/excel", params={"date_from": "2026-10-01", "date_to": "2026-10-31"})
    assert r2.status_code == 200 and "10000" in r2.text
