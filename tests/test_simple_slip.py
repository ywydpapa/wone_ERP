from tests.conftest import csrf


def _form(tok, mgr, **kw):
    data = {
        "csrf_token": tok, "direction": "지출", "slip_date": "2026-09-15",
        "amount": "10000", "purpose": "820",
        "reviewer_id": str(mgr), "approver_id": str(mgr), "save_mode": "submit",
    }
    data.update(kw)
    return data


def _lines(db, doc_id):
    return [dict(r) for r in db.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]


def test_vat_included_splits_supply_and_vat(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/slip/simple", data=_form(csrf(c, "/new_slip_simple"), seed["a"]["mgr"],
                                              amount="110000", vat_included="1"), follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    lines = _lines(db, doc)
    by_code = {l["account_code"]: l for l in lines}
    assert by_code["820"]["debit"] == 100000
    assert by_code["135"]["debit"] == 10000
    assert by_code["103"]["credit"] == 110000
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 110000


def test_income_vat_uses_vat_payable_account(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/slip/simple", data=_form(csrf(c, "/new_slip_simple"), seed["a"]["mgr"],
                                              direction="수입", purpose="401",
                                              amount="55000", vat_included="1"), follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    lines = _lines(db, doc)
    by_code = {l["account_code"]: l for l in lines}
    assert by_code["401"]["credit"] == 50000
    assert by_code["255"]["credit"] == 5000
    assert by_code["103"]["debit"] == 55000
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 55000


def test_fee_adds_to_expense_outflow(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/slip/simple", data=_form(csrf(c, "/new_slip_simple"), seed["a"]["mgr"],
                                              amount="10000", fee_amount="500"), follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    lines = _lines(db, doc)
    by_code = {l["account_code"]: l for l in lines}
    assert by_code["820"]["debit"] == 10000
    assert by_code["821"]["debit"] == 500
    assert by_code["103"]["credit"] == 10500
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 10500


def test_fee_deducted_from_income_deposit(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/slip/simple", data=_form(csrf(c, "/new_slip_simple"), seed["a"]["mgr"],
                                              direction="수입", purpose="401",
                                              amount="100000", fee_amount="2000"), follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    lines = _lines(db, doc)
    by_code = {l["account_code"]: l for l in lines}
    assert by_code["103"]["debit"] == 98000
    assert by_code["821"]["debit"] == 2000
    assert by_code["401"]["credit"] == 100000
    assert sum(l["debit"] for l in lines) == sum(l["credit"] for l in lines) == 100000


def test_fee_exceeding_income_amount_rejected(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/slip/simple", data=_form(csrf(c, "/new_slip_simple"), seed["a"]["mgr"],
                                              direction="수입", purpose="401",
                                              amount="1000", fee_amount="1000"))
    assert r.status_code == 400


def test_bank_account_sets_cash_side_account(db, seed, login):
    a = seed["a"]["company"]
    bank_id = db.execute(
        "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) VALUES (?,?,?,?,?)",
        (a, "국민은행", "123-456", "법인 당좌예금", "102"),
    ).lastrowid
    db.commit()
    c = login("a_wk")
    r = c.post("/api/slip/simple", data=_form(csrf(c, "/new_slip_simple"), seed["a"]["mgr"],
                                              amount="10000", bank_account_id=str(bank_id)), follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    lines = _lines(db, doc)
    by_code = {l["account_code"]: l for l in lines}
    assert "103" not in by_code
    assert by_code["102"]["credit"] == 10000


def test_api_bank_accounts_scoped_to_company(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) VALUES (?,?,?,?,?)",
               (a, "국민은행", "111", "A계좌", "103"))
    db.execute("INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) VALUES (?,?,?,?,?)",
               (b, "신한은행", "222", "B계좌", "103"))
    db.commit()
    c = login("a_wk")
    data = c.get("/api/bank_accounts").json()
    assert len(data) == 1 and data[0]["bank"] == "국민은행" and data[0]["code"] == "111"
