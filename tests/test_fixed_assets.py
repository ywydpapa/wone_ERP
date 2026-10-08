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
    assert assets.depr(db, a, 2026)["amount"] == 1_500_000
    assert assets.year_amount(a, 2027, 1_500_000) == 2_000_000
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
    assert d["accum"] == 6_000_000 and d["amount"] == 2_000_000


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
    assert ("816", 1_500_000, 0) in lines and ("211", 0, 1_500_000) in lines
    assert ("451", 500_000, 0) in lines and ("120", 0, 500_000) in lines
    assert db.execute("SELECT amount FROM fa_depr WHERE asset_id=?", (asset["id"],)).fetchone()[0] == 1_500_000
    assert c.post("/fi/year-end", data={"csrf_token": tok, "year": "2026"}).status_code == 400
    assert assets.depr(db, asset, 2027)["amount"] == 2_000_000

    r = c.request("DELETE", "/fi/year-end/2026", data={"csrf_token": tok})
    assert r.json()["ok"]
    assert not db.execute("SELECT 1 FROM fa_depr").fetchone()
    assert not db.execute("SELECT 1 FROM erp_docs WHERE id=?", (doc["id"],)).fetchone()


def test_fiscal_close_locks_year(db, seed, login):
    a = seed["a"]["company"]
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
    assert "1,500,000" in c.get("/fa?year=2026").text
