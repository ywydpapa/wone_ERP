from core import assets, books
from tests.conftest import csrf


def _asset(db, company, **kw):
    a = {"code": "00001", "name": "노트북", "account_code": "206", "acq_date": "2026-04-15", "acq_cost": 10_000_000,
         "life_years": 5, "method": "정액법", "open_accum": 0, "open_year": 2025}
    a.update(kw)
    fa_id = db.execute(
        """INSERT INTO fixed_assets (company_id, code, name, account_code, acq_date, acq_cost, life_years, method, open_accum, open_year)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (company, a["code"], a["name"], a["account_code"], a["acq_date"], a["acq_cost"], a["life_years"], a["method"],
         a["open_accum"], a["open_year"]),
    ).lastrowid
    db.commit()
    return db.execute("SELECT * FROM fixed_assets WHERE id=?", (fa_id,)).fetchone()


def test_straight_line_monthly(db, seed):
    a = _asset(db, seed["a"]["company"])
    assert assets.depr(db, a, 2026)["amount"] == 1_499_850
    assert assets.year_amount(a, 2027, 1_500_000) == 1_999_800
    assert assets.year_amount(a, 2031, 8_500_000) == 1_499_000


def test_declining_balance(db, seed):
    a = _asset(db, seed["a"]["company"], method="정률법", acq_date="2026-01-02")
    assert assets.year_amount(a, 2026, 0) == 4_510_000
    assert assets.year_amount(a, 2027, 4_510_000) == 2_475_990


def test_gap_year_blocks(db, seed):
    a = _asset(db, seed["a"]["company"])
    assert assets.depr(db, a, 2027)["error"] == "2026년 상각 미반영"


def test_open_accum(db, seed):
    a = _asset(db, seed["a"]["company"], acq_date="2023-01-01", open_accum=6_000_000, open_year=2025)
    d = assets.depr(db, a, 2026)
    assert d["accum"] == 6_000_000 and d["amount"] == 1_999_800


def test_straight_line_last_year_memo(db, seed):
    # 7년이면 1000//7=142로 매년 0.6% 덜 깎여 만기에도 비망가액까지 안 떨어지던 문제
    a = _asset(db, seed["a"]["company"], acq_date="2020-01-01", life_years=7, acq_cost=7_000_000, open_year=2019)
    acc = 999_857 * 6
    amt = assets.year_amount(a, 2026, acc)
    assert amt == 999_858
    assert a["acq_cost"] - acc - amt == 1000


def test_capex_raises_future_depr(db, seed):
    company = seed["a"]["company"]
    a = _asset(db, company, acq_date="2024-01-01", life_years=5, acq_cost=10_000_000, open_year=2023)
    db.execute("INSERT INTO fa_depr (company_id, asset_id, year, amount) VALUES (?,?,2024,1999800)", (company, a["id"]))
    db.execute("INSERT INTO fa_capex (company_id, asset_id, date, amount) VALUES (?,?,'2024-06-01',2000000)",
              (company, a["id"]))
    db.commit()
    assert assets.depr(db, a, 2025)["amount"] == 2_399_800


def test_capex_route(db, seed, login):
    a = seed["a"]["company"]
    asset = _asset(db, a, acq_date="2024-01-01", open_year=2023)
    db.execute("INSERT INTO fa_depr (company_id, asset_id, year, amount) VALUES (?,?,2024,1999800)", (a, asset["id"]))
    db.commit()
    c = login("a_mgr")
    tok = csrf(c, f"/fa/{asset['id']}")
    r = c.post(f"/fa/{asset['id']}/capex", data={"csrf_token": tok, "date": "2024-06-01", "amount": "2,000,000",
                                                 "memo": "증설"}, follow_redirects=False)
    assert r.status_code == 400
    r = c.post(f"/fa/{asset['id']}/capex", data={"csrf_token": tok, "date": "2025-06-01", "amount": "2,000,000",
                                                 "memo": "증설"}, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT amount FROM fa_capex WHERE asset_id=?", (asset["id"],)).fetchone()[0] == 2_000_000
    assert assets.depr(db, asset, 2025)["amount"] == 2_399_800
    assert "2,000,000" in c.get(f"/fa/{asset['id']}").text


def test_asset_crud(db, seed, login):
    c = login("a_mgr")
    form = {"csrf_token": csrf(c, "/fa/new"), "name": "복합기", "account_code": "206", "acq_date": "2026-03-01",
            "acq_cost": "3,000,000", "life_years": "5", "method": "정액법", "open_accum": "0", "status": "active"}
    r = c.post("/fa", data=form, follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT * FROM fixed_assets WHERE company_id=?", (seed["a"]["company"],)).fetchone()
    assert row["code"] == "00001" and row["acq_cost"] == 3_000_000 and row["open_year"] == 2025
    assert c.post("/fa", data=dict(form, account_code="401")).status_code == 400
    assert c.post("/fa", data=dict(form, method="정률법", life_years="30")).status_code == 400
    assert "복합기" not in login("b_mgr").get("/fa").text
    assert login("b_mgr").get(f"/fa/{row['id']}").status_code == 404
    w = login("a_wk")
    assert w.post("/fa", data=dict(form, csrf_token=csrf(w))).status_code == 403


def test_year_end_slip(db, seed, login):
    a = seed["a"]["company"]
    asset = _asset(db, a)
    books.post(db, a, seed["a"]["mgr"], "2026-05-01",
               [{"code": "120", "debit": 800_000, "credit": 0}, {"code": "103", "debit": 0, "credit": 800_000}], "매입", "manual")
    db.commit()
    c = login("a_mgr")
    tok = csrf(c, "/fi/year-end")
    r = c.post("/fi/year-end", data={"csrf_token": tok, "year": "2026", "rate": "1", "end_stock": "300,000"}, follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT * FROM erp_docs WHERE company_id=? AND source_type='closing'", (a,)).fetchone()
    assert doc["slip_date"] == "2026-12-31"
    lines = {(l["account_code"], l["debit"], l["credit"]) for l in db.execute("SELECT * FROM slip_lines WHERE doc_id=?", (doc["id"],))}
    assert ("816", 1_499_850, 0) in lines and ("211", 0, 1_499_850) in lines
    assert ("451", 500_000, 0) in lines and ("120", 0, 500_000) in lines
    assert db.execute("SELECT amount FROM fa_depr WHERE asset_id=?", (asset["id"],)).fetchone()[0] == 1_499_850
    assert c.post("/fi/year-end", data={"csrf_token": tok, "year": "2026"}).status_code == 400
    assert assets.depr(db, asset, 2027)["amount"] == 1_999_800

    r = c.request("DELETE", "/fi/year-end/2026", data={"csrf_token": tok})
    assert r.json()["ok"]
    assert not db.execute("SELECT 1 FROM fa_depr").fetchone()
    assert not db.execute("SELECT 1 FROM erp_docs WHERE id=?", (doc["id"],)).fetchone()


def _closing_entry(db, book, uid, year):
    books.post(db, book, uid, f"{year}-12-31",
              [{"code": "816", "debit": 100, "credit": 0}, {"code": "211", "debit": 0, "credit": 100}],
              f"{year}년 결산분개", "closing", year)
    db.commit()


def test_fiscal_close_locks_year(db, seed, login):
    a = seed["a"]["company"]
    _closing_entry(db, a, seed["a"]["mgr"], 2025)
    c = login("a_mgr")
    tok = csrf(c, "/fi/fiscal")
    assert c.post("/fi/fiscal", data={"csrf_token": tok, "year": "2025"}).json()["ok"]
    assert books.period_closed(db, a, "2025-07-01")
    assert not books.period_closed(db, seed["b"]["company"], "2025-07-01")
    r = c.request("DELETE", "/fi/fiscal/2025", data={"csrf_token": tok, "reason": "수정", "password": "x"})
    assert r.status_code == 400
    r = c.request("DELETE", "/fi/fiscal/2025", data={"csrf_token": tok, "reason": "수정", "password": "1234"})
    assert r.json()["ok"]
    assert not books.period_closed(db, a, "2025-07-01")


def test_fiscal_close_requires_closing_doc(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_mgr")
    tok = csrf(c, "/fi/fiscal")
    r = c.post("/fi/fiscal", data={"csrf_token": tok, "year": "2025"})
    assert r.status_code == 400 and "결산" in r.json()["error"]
    _closing_entry(db, a, seed["a"]["mgr"], 2025)
    assert c.post("/fi/fiscal", data={"csrf_token": tok, "year": "2025"}).json()["ok"]


def test_fiscal_close_in_order(db, seed, login):
    a = seed["a"]["company"]
    books.post(db, a, seed["a"]["mgr"], "2024-03-01",
               [{"code": "813", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}], "x", "manual")
    db.commit()
    c = login("a_mgr")
    tok = csrf(c, "/fi/fiscal")
    r = c.post("/fi/fiscal", data={"csrf_token": tok, "year": "2025"})
    assert r.status_code == 400 and "2024" in r.json()["error"]
    assert c.post("/fi/fiscal", data={"csrf_token": tok, "year": "2099"}).status_code == 400


def test_pages_render(db, seed, login):
    _asset(db, seed["a"]["company"])
    c = login("a_mgr")
    for url in ("/fa", "/fa?year=2026&status=all", "/fa/new", "/fi/year-end?year=2026&rate=1.5&end_stock=100", "/fi/fiscal"):
        r = c.get(url)
        assert r.status_code == 200, url
    assert "1,499,850" in c.get("/fa?year=2026").text


def test_disposal_cancel_restores_status(db, seed, login):
    a = seed["a"]["company"]
    asset = _asset(db, a)
    c = login("a_mgr")
    tok = csrf(c, f"/fa/{asset['id']}/disposal")
    r = c.post(
        f"/fa/{asset['id']}/disposal",
        data={"csrf_token": tok, "disposed_date": "2026-06-30", "supply_amt": "5,000,000",
              "vat_amt": "0", "deposit_code": "103"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    row = db.execute("SELECT status, disposed_date FROM fixed_assets WHERE id=?", (asset["id"],)).fetchone()
    assert row["status"] == "disposed"
    doc = db.execute(
        "SELECT * FROM erp_docs WHERE company_id=? AND source_type='fa_disposal' AND source_id=?",
        (a, asset["id"]),
    ).fetchone()
    assert doc
    assert db.execute("SELECT 1 FROM fa_depr WHERE doc_id=?", (doc["id"],)).fetchone()

    tok2 = csrf(c, f"/fa/{asset['id']}")
    bad = c.request("DELETE", f"/fa/{asset['id']}/disposal", data={"csrf_token": tok2, "reason": "오류", "password": "wrong"})
    assert bad.status_code == 400
    row = db.execute("SELECT status FROM fixed_assets WHERE id=?", (asset["id"],)).fetchone()
    assert row["status"] == "disposed"

    ok = c.request("DELETE", f"/fa/{asset['id']}/disposal", data={"csrf_token": tok2, "reason": "오류", "password": "1234"})
    assert ok.json()["ok"]
    row2 = db.execute("SELECT status, disposed_date FROM fixed_assets WHERE id=?", (asset["id"],)).fetchone()
    assert row2["status"] == "active" and row2["disposed_date"] is None
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE reversal_of=?", (doc["id"],)).fetchone()[0] == 1
    assert not db.execute("SELECT 1 FROM fa_depr WHERE doc_id=?", (doc["id"],)).fetchone()


def test_disposal_cancel_blocked_when_fiscal_closed(db, seed, login):
    a = seed["a"]["company"]
    asset = _asset(db, a)
    c = login("a_mgr")
    tok = csrf(c, f"/fa/{asset['id']}/disposal")
    c.post(
        f"/fa/{asset['id']}/disposal",
        data={"csrf_token": tok, "disposed_date": "2026-06-30", "supply_amt": "0", "vat_amt": "0", "deposit_code": ""},
    )
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,6,'closed')", (a,))
    db.commit()

    tok2 = csrf(c, f"/fa/{asset['id']}")
    r = c.request("DELETE", f"/fa/{asset['id']}/disposal", data={"csrf_token": tok2, "reason": "사유", "password": "1234"})
    assert r.status_code == 400
    assert "마감" in r.json()["error"]
    row = db.execute("SELECT status FROM fixed_assets WHERE id=?", (asset["id"],)).fetchone()
    assert row["status"] == "disposed"


def test_disposal_cancel_other_book_404(db, seed, login):
    b = seed["b"]["company"]
    asset = _asset(db, b)
    cb = login("b_mgr")
    tok = csrf(cb, f"/fa/{asset['id']}/disposal")
    cb.post(
        f"/fa/{asset['id']}/disposal",
        data={"csrf_token": tok, "disposed_date": "2026-06-30", "supply_amt": "0", "vat_amt": "0", "deposit_code": ""},
    )

    ca = login("a_mgr")
    tok2 = csrf(ca, "/fa")
    r = ca.request("DELETE", f"/fa/{asset['id']}/disposal", data={"csrf_token": tok2, "reason": "사유", "password": "1234"})
    assert r.status_code == 404
