from tests.conftest import csrf


def _partner(db, book, code="P1"):
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES (?,?,?)", (code, "거래처" + code, book)).lastrowid
    db.commit()
    return pid


def _post(c, **kw):
    data = {"csrf_token": csrf(c, "/tax-invoices/new"), "tax_type": "과세", "evidence": "세금계산서",
            "issue_date": "2026-09-20", "line_count": "1", "is_electronic": "1", "deduct": "1",
            "save_mode": "detail"}
    data.update({k: str(v) for k, v in kw.items()})
    return c.post("/tax-invoices", data=data, follow_redirects=False)


def test_fail_rerenders_form_with_input(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    pid = _partner(db, a, "P1")
    r = _post(c, kind="매출", partner_id=pid, acct="120", pay="110",
              item_name_1="테스트품목", item_supply_1="10,000")
    assert r.status_code == 400
    assert "테스트품목" in r.text
    assert "거래처P1" in r.text
    assert "계정을 확인해 주세요." in r.text
    assert db.execute("SELECT COUNT(*) FROM tax_invoices").fetchone()[0] == 0


def test_save_and_new_redirects_to_new_form(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    pid = _partner(db, a)
    r = _post(c, kind="매출", partner_id=pid, acct="401", pay="110", item_supply_1="10000", save_mode="new")
    assert r.status_code == 303
    assert r.headers["location"] == "/tax-invoices/new"
    assert db.execute("SELECT COUNT(*) FROM tax_invoices").fetchone()[0] == 1


def test_save_default_redirects_to_detail(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    pid = _partner(db, a)
    r = _post(c, kind="매출", partner_id=pid, acct="401", pay="110", item_supply_1="10000")
    inv_id = db.execute("SELECT id FROM tax_invoices").fetchone()[0]
    assert r.status_code == 303
    assert r.headers["location"] == f"/tax-invoices/{inv_id}"


def test_new_form_markup(db, seed, login):
    c = login("a_wk")
    r = c.get("/tax-invoices/new")
    assert r.status_code == 200
    assert r.text.count('data-lookup="account"') == 2
    assert 'data-action="copyLine"' in r.text
    assert "저장 후 신규" in r.text
    assert "F2 계정/거래처 검색" in r.text
    assert "syncEvidence" in r.text


def test_list_status_badge_done(db, seed, login):
    from routers.erp_sales import _create_ship_slip
    a = seed["a"]["company"]
    pid = _partner(db, a, "C1")
    _create_ship_slip(db, a, 1, "SH-1", 10000, seed["a"]["wk"], "2026-09-20", pid,
                      [{"name": "품목1", "qty": 10, "unit_price": 1000, "supply_amt": 10000}])
    db.commit()
    c = login("a_mgr")
    r = c.get("/tax-invoices?date_from=2026-09-01&date_to=2026-09-30")
    assert 'status-done">정상' in r.text


def test_list_pagination(db, seed, login):
    a = seed["a"]["company"]
    pid = _partner(db, a)
    for _ in range(35):
        db.execute(
            "INSERT INTO tax_invoices (company_id, kind, issue_date, partner_id, supply_amt, vat, total) VALUES (?,?,?,?,?,?,?)",
            (a, "매출", "2026-09-10", pid, 1000, 100, 1100),
        )
    db.commit()
    c = login("a_mgr")
    r1 = c.get("/tax-invoices?date_from=2026-09-01&date_to=2026-09-30")
    assert r1.status_code == 200 and 'class="pagination' in r1.text
    r2 = c.get("/tax-invoices?date_from=2026-09-01&date_to=2026-09-30&page=2")
    assert r2.status_code == 200


def test_excel_scoped_to_company(db, seed, login):
    from routers.erp_sales import _create_ship_slip
    a, b = seed["a"]["company"], seed["b"]["company"]
    pid_a = _partner(db, a, "CA")
    pid_b = _partner(db, b, "CB")
    _create_ship_slip(db, a, 1, "SH-A", 10000, seed["a"]["wk"], "2026-09-20", pid_a,
                      [{"name": "A품목", "qty": 1, "unit_price": 10000, "supply_amt": 10000}])
    _create_ship_slip(db, b, 1, "SH-B", 20000, seed["b"]["wk"], "2026-09-20", pid_b,
                      [{"name": "B품목", "qty": 1, "unit_price": 20000, "supply_amt": 20000}])
    db.commit()
    c = login("a_mgr")
    r = c.get("/tax-invoices/excel?date_from=2026-09-01&date_to=2026-09-30")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "거래처CA" in r.text
    assert "거래처CB" not in r.text


def test_excel_declared_before_detail_route(db, seed, login):
    c = login("a_mgr")
    r = c.get("/tax-invoices/excel")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]


def test_print_keeps_vat_column_for_zero_rate(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    pid = _partner(db, a, "Z1")
    r = _post(c, kind="매출", partner_id=pid, acct="401", pay="110", tax_type="영세",
              item_supply_1="10000", item_vat_1="0")
    assert r.status_code == 303
    inv_id = db.execute("SELECT id FROM tax_invoices").fetchone()[0]
    page = c.get(f"/tax-invoices/{inv_id}/print")
    assert "세 액" in page.text
    assert ">월<" in page.text and ">일<" in page.text


def test_print_hides_vat_column_for_bill(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    pid = _partner(db, a, "F1")
    r = _post(c, kind="매출", partner_id=pid, acct="401", pay="110", tax_type="면세", evidence="계산서",
              item_supply_1="10000", item_vat_1="0")
    assert r.status_code == 303
    inv_id = db.execute("SELECT id FROM tax_invoices").fetchone()[0]
    page = c.get(f"/tax-invoices/{inv_id}/print")
    assert "세 액" not in page.text
