from routers.erp_sales import _create_ship_slip
from tests.conftest import csrf


def _ship(db, seed, key="a"):
    book = seed[key]["company"]
    pid = db.execute(
        "INSERT INTO partners (code, name, company_id, biz_no) VALUES ('C1','한빛상사',?,'222-33-44444')", (book,)
    ).lastrowid
    doc = _create_ship_slip(db, book, 1, "SH-1", 10000, seed[key]["wk"], "2026-09-20", pid,
                            [{"name": "품목1", "qty": 10, "unit_price": 1000, "supply_amt": 10000}])
    db.execute("UPDATE client_companies SET business_no='111-22-33333', biz_type='제조', biz_item='전자' WHERE id=?", (book,))
    db.commit()
    inv_id = db.execute("SELECT id FROM tax_invoices WHERE doc_id=?", (doc,)).fetchone()[0]
    return doc, inv_id


def test_list_and_detail(db, seed, login):
    _, inv_id = _ship(db, seed)
    c = login("a_mgr")
    r = c.get("/tax-invoices?date_from=2026-09-01&date_to=2026-09-30")
    assert r.status_code == 200 and "한빛상사" in r.text and "11,000" in r.text
    assert c.get(f"/tax-invoices/{inv_id}").status_code == 200


def test_print_uses_invoice_and_company(db, seed, login):
    doc, inv_id = _ship(db, seed)
    c = login("a_mgr")
    r = c.get(f"/tax-invoices/{inv_id}/print")
    assert r.status_code == 200
    assert "가테스트" in r.text and "111-22-33333" in r.text and "(주)원플러스" not in r.text
    assert "1,000" in r.text and "품목1" in r.text
    r = c.get(f"/erp_doc/{doc}/tax_invoice", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/tax-invoices/{inv_id}/print"


def test_other_company_404(db, seed, login):
    doc, inv_id = _ship(db, seed, "b")
    c = login("a_mgr")
    assert c.get(f"/tax-invoices/{inv_id}").status_code == 404
    assert c.get(f"/tax-invoices/{inv_id}/print").status_code == 404
    assert c.get(f"/erp_doc/{doc}/tax_invoice", follow_redirects=False).status_code == 404
    assert "한빛상사" not in c.get("/tax-invoices?date_from=2026-09-01&date_to=2026-09-30").text


def test_vat_pages(db, seed, login):
    _ship(db, seed)
    c = login("a_mgr")
    r = c.get("/tax/vat-return?date_from=2026-07-01&date_to=2026-09-30")
    assert r.status_code == 200 and "1,000" in r.text
    r = c.get("/tax/sales-summary?date_from=2026-07-01&date_to=2026-09-30")
    assert "한빛상사" in r.text and "10,000" in r.text
    assert c.get("/tax/purchase-summary").status_code == 200
    assert c.get("/tax/vat-estimate").status_code == 404


def test_trade_statement_company(db, seed, login):
    doc, _ = _ship(db, seed)
    r = login("a_mgr").get(f"/erp_doc/{doc}/trade_statement")
    assert "가테스트" in r.text and "품목1" in r.text


def _partner(db, book, code="P1"):
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES (?,?,?)", (code, "거래처" + code, book)).lastrowid
    db.commit()
    return pid


def _post(c, **kw):
    data = {"csrf_token": csrf(c, "/tax-invoices/new"), "tax_type": "과세", "evidence": "세금계산서",
            "issue_date": "2026-09-20", "line_count": "1,2", "is_electronic": "1", "deduct": "1"}
    data.update({k: str(v) for k, v in kw.items()})
    return c.post("/tax-invoices", data=data, follow_redirects=False)


def test_manual_sales(db, seed, login):
    a = seed["a"]["company"]
    pid = _partner(db, a)
    r = _post(login("a_wk"), kind="매출", partner_id=pid, item_supply_1="10,000", item_vat_1="1,000",
              acct="401", pay="110", receipt_type="영수", remark="선결제")
    assert r.status_code == 303
    inv = db.execute("SELECT * FROM tax_invoices WHERE company_id=?", (a,)).fetchone()
    assert (inv["supply_amt"], inv["vat"], inv["source_type"]) == (10000, 1000, "manual")
    d = db.execute("SELECT status, source_type, source_id FROM erp_docs WHERE id=?", (inv["doc_id"],)).fetchone()
    assert tuple(d) == ("done", "tax", inv["id"])
    assert r.headers["location"] == f"/tax-invoices/{inv['id']}"
    assert (inv["receipt_type"], inv["remark"]) == ("영수", "선결제")


def test_manual_items(db, seed, login):
    a = seed["a"]["company"]
    r = _post(login("a_wk"), kind="매출", partner_id=_partner(db, a), acct="401", pay="110",
              item_month_1=9, item_day_1=3, item_name_1="A", item_qty_1=2, item_price_1="1,500", item_supply_1=3000,
              item_vat_1=300, item_name_2="B", item_qty_2=1, item_price_2=2000, item_supply_2=2000, item_vat_2=199,
              item_note_2="할인")
    assert r.status_code == 303
    inv = db.execute("SELECT id, supply_amt, vat FROM tax_invoices").fetchone()
    assert (inv["supply_amt"], inv["vat"]) == (5000, 499)
    items = db.execute("SELECT item_date, vat, note FROM tax_invoice_items WHERE invoice_id=? ORDER BY line_no",
                       (inv["id"],)).fetchall()
    assert [tuple(r) for r in items] == [("2026-09-03", 300, ""), ("2026-09-20", 199, "할인")]


def test_manual_purchase_nondeduct(db, seed, login):
    a = seed["a"]["company"]
    _post(login("a_wk"), kind="매입", partner_id=_partner(db, a), item_supply_1=5000, item_vat_1=500,
          acct="811", pay="251", deduct="0")
    inv = db.execute("SELECT * FROM tax_invoices").fetchone()
    codes = [r[0] for r in db.execute("SELECT account_code FROM slip_lines WHERE doc_id=? ORDER BY line_no", (inv["doc_id"],))]
    assert (inv["deduct"], codes) == (0, ["811", "251"])


def test_manual_rejects(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    c = login("a_wk")
    other = _partner(db, b, "X1")
    assert _post(c, kind="매출", partner_id=other, item_supply_1=1000, acct="401", pay="110").status_code == 400
    assert _post(c, kind="매출", partner_id=_partner(db, a), item_supply_1=1000, acct="120",
                 pay="110").status_code == 400
    assert _post(c, kind="매출", partner_id=_partner(db, a, "P2"), item_supply_1=1000, acct="401", pay="110",
                 tax_type="면세").status_code == 400
    assert _post(c, kind="매출", partner_id=_partner(db, a, "P3"), item_supply_1=1000, acct="401", pay="110",
                 receipt_type="외상").status_code == 400
    assert db.execute("SELECT COUNT(*) FROM tax_invoices").fetchone()[0] == 0


def test_amend_and_approval_routes(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_mgr")
    _post(c, kind="매입", partner_id=_partner(db, a), item_supply_1=5000, item_vat_1=500, acct="120", pay="251")
    inv_id = db.execute("SELECT id FROM tax_invoices").fetchone()[0]
    tok = csrf(c, f"/tax-invoices/{inv_id}")
    r = c.post(f"/tax-invoices/{inv_id}/approval", data={"csrf_token": tok, "approval_no": "20260920-41000000-00000001"},
               follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT approval_no FROM tax_invoices WHERE id=?", (inv_id,)).fetchone()[0] == "20260920-41000000-00000001"
    r = c.post(f"/tax-invoices/{inv_id}/amend", data={"csrf_token": tok, "issue_date": "2026-09-25", "supply": "0", "reason": "4"},
               follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT status FROM tax_invoices WHERE orig_id=?", (inv_id,)).fetchone()[0] == "취소"


def test_partner_save_tax_type(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_mgr")
    tok = csrf(c, "/partners/new")
    c.post("/partners/save", data={"csrf_token": tok, "code": "P9", "name": "거래처P9", "tax_type": "영세"})
    row = db.execute("SELECT tax_type FROM partners WHERE company_id=? AND code='P9'", (a,)).fetchone()
    assert row[0] == "영세"


def test_company_update_biz_type(db, seed, login):
    a = seed["a"]["company"]
    c = login("t_staff")
    tok = csrf(c, f"/platform/companies/{a}/edit")
    r = c.post(f"/platform/companies/{a}", data={"csrf_token": tok, "name": "가테스트", "biz_type": "제조"},
              follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT biz_type FROM client_companies WHERE id=?", (a,)).fetchone()[0] == "제조"


def test_amend_other_company_404(db, seed, login):
    b = seed["b"]["company"]
    _post(login("b_mgr"), kind="매출", partner_id=_partner(db, b), item_supply_1=1000, acct="401", pay="110")
    inv_id = db.execute("SELECT id FROM tax_invoices").fetchone()[0]
    c = login("a_mgr")
    tok = csrf(c, "/tax-invoices/new")
    assert c.post(f"/tax-invoices/{inv_id}/amend", data={"csrf_token": tok, "issue_date": "2026-09-25", "supply": "0", "reason": "4"}).status_code == 404
    assert c.post(f"/tax-invoices/{inv_id}/approval", data={"csrf_token": tok, "approval_no": "x"}).status_code == 404
