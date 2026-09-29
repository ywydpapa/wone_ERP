import pytest

from core import books, invoices
from routers.erp_sales import _create_ship_slip
from routers.erp_purchase import _create_gr_slip


def _partner(db, book, tax_type="과세", code="C1"):
    return db.execute(
        "INSERT INTO partners (code, name, company_id, tax_type) VALUES (?,?,?,?)",
        (code, f"거래처{code}", book, tax_type),
    ).lastrowid


def test_calc_vat():
    assert invoices.calc_vat(10000) == 1000
    assert invoices.calc_vat(10009) == 1000
    assert invoices.calc_vat(-2005) == -200


def test_split_total():
    assert invoices.split_total(11000) == (10000, 1000)
    assert invoices.split_total(10999) == (9999, 1000)


def test_terms(db, seed):
    a = seed["a"]["company"]
    assert invoices.terms(db, _partner(db, a), 10000) == ("과세", "세금계산서", 1000)
    assert invoices.terms(db, _partner(db, a, "영세", "C2"), 10000) == ("영세", "세금계산서", 0)
    assert invoices.terms(db, _partner(db, a, "면세", "C3"), 10000) == ("면세", "계산서", 0)


def _inv(kind, supply, vat, pid, deduct=1):
    return {"kind": kind, "supply_amt": supply, "vat": vat, "partner_id": pid, "deduct": deduct}


def _rows(lines):
    return [(l["code"], l["debit"], l["credit"]) for l in lines]


def test_inv_lines_sales():
    assert _rows(invoices.inv_lines(_inv("매출", 10000, 1000, 1), "401", "110", "s")) == [
        ("110", 11000, 0), ("401", 0, 10000), ("255", 0, 1000)]


def test_inv_lines_purchase():
    assert _rows(invoices.inv_lines(_inv("매입", 5000, 500, 1), "120", "251", "s")) == [
        ("120", 5000, 0), ("135", 500, 0), ("251", 0, 5500)]


def test_inv_lines_nondeduct():
    assert _rows(invoices.inv_lines(_inv("매입", 5000, 500, 1, deduct=0), "811", "251", "s")) == [
        ("811", 5500, 0), ("251", 0, 5500)]


def test_inv_lines_zero_vat_and_negative():
    assert _rows(invoices.inv_lines(_inv("매출", 10000, 0, 1), "401", "110", "s")) == [
        ("110", 10000, 0), ("401", 0, 10000)]
    assert _rows(invoices.inv_lines(_inv("매출", -2000, -200, 1), "401", "110", "s")) == [
        ("110", 0, 2200), ("401", 2000, 0), ("255", 200, 0)]


def test_add_items_vat_sum(db, seed):
    a = seed["a"]["company"]
    pid = _partner(db, a)
    items = [{"name": f"품목{i}", "qty": 1, "unit_price": 3335, "supply_amt": 3335} for i in range(3)]
    inv_id = invoices.add(db, a, seed["a"]["wk"], {
        "kind": "매출", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-09-20",
        "partner_id": pid, "supply_amt": 10005, "vat": 1000, "doc_id": None}, items)
    inv = db.execute("SELECT * FROM tax_invoices WHERE id=?", (inv_id,)).fetchone()
    assert (inv["company_id"], inv["total"], inv["status"]) == (a, 11005, "정상")
    vats = [r[0] for r in db.execute("SELECT vat FROM tax_invoice_items WHERE invoice_id=? ORDER BY line_no", (inv_id,))]
    assert vats == [333, 333, 334]


def test_add_items_zero_vat(db, seed):
    a = seed["a"]["company"]
    inv_id = invoices.add(db, a, seed["a"]["wk"], {
        "kind": "매출", "tax_type": "영세", "evidence": "세금계산서", "issue_date": "2026-09-20",
        "partner_id": _partner(db, a), "supply_amt": 6670, "vat": 0, "doc_id": None},
        [{"name": "A", "supply_amt": 3335}, {"name": "B", "supply_amt": 3335}])
    assert [r[0] for r in db.execute("SELECT vat FROM tax_invoice_items WHERE invoice_id=?", (inv_id,))] == [0, 0]


def _lines(db, doc_id):
    return [(r["account_code"], r["debit"], r["credit"])
            for r in db.execute("SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,))]


def test_ship_splits_vat(db, seed):
    a = seed["a"]["company"]
    pid = _partner(db, a)
    items = [{"name": "품목1", "qty": 10, "unit_price": 1000, "supply_amt": 10000}]
    doc = _create_ship_slip(db, a, 7, "SH-7", 10000, seed["a"]["wk"], "2026-09-20", pid, items)
    assert _lines(db, doc) == [("110", 11000, 0), ("401", 0, 10000), ("255", 0, 1000)]
    inv = db.execute("SELECT * FROM tax_invoices WHERE doc_id=?", (doc,)).fetchone()
    assert (inv["kind"], inv["evidence"], inv["supply_amt"], inv["vat"], inv["total"]) == ("매출", "세금계산서", 10000, 1000, 11000)
    assert (inv["source_type"], inv["source_id"], inv["company_id"], inv["partner_id"]) == ("ship", 7, a, pid)
    assert db.execute("SELECT COUNT(*) FROM tax_invoice_items WHERE invoice_id=?", (inv["id"],)).fetchone()[0] == 1


def test_ship_zero_rated_and_exempt(db, seed):
    a = seed["a"]["company"]
    doc = _create_ship_slip(db, a, 8, "SH-8", 10000, seed["a"]["wk"], "2026-09-20", _partner(db, a, "영세", "C2"))
    assert _lines(db, doc) == [("110", 10000, 0), ("401", 0, 10000)]
    doc = _create_ship_slip(db, a, 9, "SH-9", 10000, seed["a"]["wk"], "2026-09-20", _partner(db, a, "면세", "C3"))
    inv = db.execute("SELECT evidence, vat FROM tax_invoices WHERE doc_id=?", (doc,)).fetchone()
    assert tuple(inv) == ("계산서", 0)


def test_gr_splits_vat(db, seed):
    a = seed["a"]["company"]
    doc = _create_gr_slip(db, a, 3, "GR-3", 5000, seed["a"]["wk"], "2026-09-20", _partner(db, a))
    assert _lines(db, doc) == [("120", 5000, 0), ("135", 500, 0), ("251", 0, 5500)]
    inv = db.execute("SELECT * FROM tax_invoices WHERE doc_id=?", (doc,)).fetchone()
    assert (inv["kind"], inv["vat"], inv["approval_no"], inv["source_type"]) == ("매입", 500, "", "gr")


def test_auto_invoice_rolled_back_when_closed(db, seed):
    a = seed["a"]["company"]
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,9,'closed')", (a,))
    with pytest.raises(ValueError):
        _create_ship_slip(db, a, 1, "SH-1", 1000, seed["a"]["wk"], "2026-09-20", _partner(db, a))
    assert db.execute("SELECT COUNT(*) FROM tax_invoices").fetchone()[0] == 0


def test_amend_and_cancel(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    doc = _create_ship_slip(db, a, 7, "SH-7", 10000, uid, "2026-09-20", _partner(db, a))
    orig = db.execute("SELECT id FROM tax_invoices WHERE doc_id=?", (doc,)).fetchone()[0]

    mid = invoices.amend(db, a, uid, orig, "2026-09-25", 8000)
    m = db.execute("SELECT * FROM tax_invoices WHERE id=?", (mid,)).fetchone()
    assert (m["status"], m["orig_id"], m["supply_amt"], m["vat"], m["total"]) == ("수정", orig, -2000, -200, -2200)
    assert _lines(db, m["doc_id"]) == [("110", 0, 2200), ("401", 2000, 0), ("255", 200, 0)]

    cid = invoices.amend(db, a, uid, orig, "2026-09-26", 0)
    c = db.execute("SELECT * FROM tax_invoices WHERE id=?", (cid,)).fetchone()
    assert (c["status"], c["supply_amt"], c["vat"]) == ("취소", -8000, -800)

    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, orig, "2026-09-27", 5000)
    with pytest.raises(ValueError):
        invoices.amend(db, a, uid, mid, "2026-09-27", 5000)


def test_amend_total_based_mixed_sign_balances(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = _partner(db, a)
    supply, vat = invoices.split_total(10998)
    inv = {"kind": "매출", "tax_type": "과세", "evidence": "세금계산서", "issue_date": "2026-09-20",
           "partner_id": pid, "supply_amt": supply, "vat": vat, "deduct": 1}
    doc = books.post(db, a, uid, "2026-09-20", invoices.inv_lines(inv, "401", "110", "t"), "t", "tax")
    orig = invoices.add(db, a, uid, {**inv, "doc_id": doc})

    mid = invoices.amend(db, a, uid, orig, "2026-09-25", 9999)
    m = db.execute("SELECT * FROM tax_invoices WHERE id=?", (mid,)).fetchone()
    assert (m["supply_amt"], m["vat"]) == (1, -1)
    lines = _lines(db, m["doc_id"])
    assert lines == [("401", 0, 1), ("255", 1, 0)]
    assert sum(l[1] for l in lines) == sum(l[2] for l in lines)


def test_amend_other_book(db, seed):
    a, b = seed["a"]["company"], seed["b"]["company"]
    doc = _create_ship_slip(db, a, 7, "SH-7", 10000, seed["a"]["mgr"], "2026-09-20", _partner(db, a))
    orig = db.execute("SELECT id FROM tax_invoices WHERE doc_id=?", (doc,)).fetchone()[0]
    with pytest.raises(ValueError):
        invoices.amend(db, b, seed["b"]["mgr"], orig, "2026-09-25", 0)


def _mk(db, book, uid, kind, supply, vat, pid, evidence="세금계산서", tax_type="과세", deduct=1, electronic=1):
    inv = {"kind": kind, "tax_type": tax_type, "evidence": evidence, "issue_date": "2026-08-10",
           "partner_id": pid, "supply_amt": supply, "vat": vat, "deduct": deduct, "is_electronic": electronic}
    acct, pay = ("401", "110") if kind == "매출" else ("120", "251")
    doc = books.post(db, book, uid, "2026-08-10", invoices.inv_lines(inv, acct, pay, "t"), "t", "tax")
    return invoices.add(db, book, uid, {**inv, "doc_id": doc})


def test_vat_return(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    p1, p2 = _partner(db, a), _partner(db, a, code="C2")
    _mk(db, a, uid, "매출", 100000, 10000, p1)
    _mk(db, a, uid, "매출", 50000, 0, p2, tax_type="영세")
    _mk(db, a, uid, "매입", 40000, 4000, p1)
    _mk(db, a, uid, "매입", 20000, 2000, p2, deduct=0)
    _mk(db, a, uid, "매입", 10000, 1000, p2, evidence="카드")
    r = invoices.vat_return(db, a, "2026-07-01", "2026-09-30")
    assert r["sales_vat"] == 10000
    assert r["buy_vat"] == 5000
    assert r["payable"] == 5000
    assert (r["book_255"], r["book_135"]) == (10000, 5000)
    assert r["warns"] == []


def test_vat_return_warns_on_slip_without_invoice(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = _partner(db, a)
    books.post(db, a, uid, "2026-08-10", [
        {"code": "110", "debit": 1100, "credit": 0, "partner_id": pid},
        {"code": "401", "debit": 0, "credit": 1000},
        {"code": "255", "debit": 0, "credit": 100}], "수기", "manual")
    r = invoices.vat_return(db, a, "2026-07-01", "2026-09-30")
    assert r["book_255"] == 100 and r["sales_vat"] == 0 and len(r["warns"]) == 1


def test_partner_totals(db, seed):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    p1, p2 = _partner(db, a), _partner(db, a, code="C2")
    _mk(db, a, uid, "매출", 100000, 10000, p1)
    _mk(db, a, uid, "매출", 30000, 3000, p1)
    _mk(db, a, uid, "매출", 20000, 2000, p2, electronic=0)
    _mk(db, a, uid, "매출", 5000, 500, p2, evidence="카드")
    rows, totals = invoices.partner_totals(db, a, "매출", "2026-07-01", "2026-09-30")
    assert [(r["partner_name"], r["cnt"], r["supply"]) for r in rows] == [("거래처C1", 2, 130000), ("거래처C2", 1, 20000)]
    assert totals[1] == (2, 130000, 13000) and totals[0] == (1, 20000, 2000)


def test_company_info(db, seed):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET business_no='111-22-33333', biz_type='제조', biz_item='전자' WHERE id=?", (a,))
    info = books.company_info(db, a)
    assert (info["name"], info["biz_no"], info["biz_type"], info["biz_item"]) == ("가테스트", "111-22-33333", "제조", "전자")
    assert books.company_info(db, 0)["name"] == "(주)원플러스"
