import sqlite3

import pytest

from core import books
from migrate import run_migrations
from routers.erp_accounting import _create_payroll_slip, _income_statement_data
from routers.erp_ledger import _dept_pnl_data, _dept_pnl_period
from tests.conftest import csrf


def L(code, dr=0, cr=0, **kw):
    return {"code": code, "debit": dr, "credit": cr, **kw}


def _dept(db, book, code, name, is_active=1):
    db.execute("INSERT INTO depts (company_id, code, name, is_active) VALUES (?,?,?,?)", (book, code, name, is_active))
    db.commit()


def _asset(db, company, **kw):
    a = {"code": "00001", "name": "복합기", "account_code": "206", "acq_date": "2024-01-01", "acq_cost": 12_000_000,
         "life_years": 5, "method": "정액법", "open_accum": 0, "open_year": 2023, "dept": ""}
    a.update(kw)
    fa_id = db.execute(
        """INSERT INTO fixed_assets (company_id, code, name, account_code, acq_date, acq_cost, life_years, method,
               open_accum, open_year, dept)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (company, a["code"], a["name"], a["account_code"], a["acq_date"], a["acq_cost"], a["life_years"], a["method"],
         a["open_accum"], a["open_year"], a["dept"]),
    ).lastrowid
    db.commit()
    return fa_id


def _prior_depr(db, company, asset_id, years, amount):
    for y in years:
        db.execute("INSERT INTO fa_depr (company_id, asset_id, year, amount) VALUES (?,?,?,?)",
                  (company, asset_id, y, amount))
    db.commit()


def test_backfill_depts(tmp_path):
    path = str(tmp_path / "bf.db")
    run_migrations(path, upto=102)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cid = conn.execute("INSERT INTO client_companies (name) VALUES ('가테스트')").lastrowid
    conn.execute("INSERT INTO employees (name, dept, company_id) VALUES ('가','영업팀',?)", (cid,))
    conn.execute("INSERT INTO employees (name, dept, company_id) VALUES ('나',' 영업팀 ',?)", (cid,))
    conn.execute("INSERT INTO employees (name, dept) VALUES ('스태프','총무팀')")
    conn.execute(
        """INSERT INTO fixed_assets (company_id, code, name, account_code, acq_date, acq_cost, life_years, open_year, dept)
           VALUES (?,'00001','복합기','206','2026-01-01',1000000,5,2025,'개발팀')""",
        (cid,),
    )
    doc_id = conn.execute(
        "INSERT INTO erp_docs (user_id, doc_type, status, company_id, slip_date) VALUES (1,'expense','done',?,'2026-01-01')",
        (cid,),
    ).lastrowid
    conn.execute(
        "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, dept) VALUES (?,1,'','103',1000,0,'재무팀')",
        (doc_id,),
    )
    conn.execute(
        "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, dept) VALUES (?,2,'','401',0,1000,'')",
        (doc_id,),
    )
    conn.commit()
    conn.close()

    run_migrations(path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM depts WHERE company_id=? ORDER BY code", (cid,)).fetchall()
    names = [r["name"] for r in rows]
    assert set(names) == {"영업팀", "개발팀", "재무팀"}
    assert len(names) == len(set(names))
    assert [r["code"] for r in rows] == sorted(r["code"] for r in rows)
    book0 = {r[0] for r in conn.execute("SELECT name FROM depts WHERE company_id=0")}
    assert "총무팀" in book0


def test_check_lines_dept(db, seed):
    a, b = seed["a"]["company"], seed["b"]["company"]
    _dept(db, a, "001", "영업팀")
    ok = [L("103", 1000), L("401", cr=1000, dept="영업팀")]
    assert books.check_lines(db, a, ok) is None
    assert "등록되지 않은 부서" in books.check_lines(db, a, [L("103", 1000), L("401", cr=1000, dept="재무팀")])
    assert "등록되지 않은 부서" in books.check_lines(db, b, [L("103", 1000), L("401", cr=1000, dept="영업팀")])

    db.execute("UPDATE depts SET is_active=0 WHERE company_id=? AND name='영업팀'", (a,))
    assert books.check_lines(db, a, ok) is None


def test_reverse_passes_inactive_dept(db, seed):
    a = seed["a"]["company"]
    uid = seed["a"]["mgr"]
    _dept(db, a, "001", "영업팀")
    doc_id = books.post(db, a, uid, "2026-05-01",
                        [L("103", 1000, dept="영업팀"), L("401", cr=1000)], "매출", "manual")
    db.commit()
    db.execute("UPDATE depts SET is_active=0 WHERE company_id=? AND name='영업팀'", (a,))
    db.commit()
    new_id = books.reverse(db, doc_id, uid, "2026-05-02")
    assert new_id


def test_post_rejects_unknown_dept(db, seed):
    a = seed["a"]["company"]
    with pytest.raises(ValueError, match="등록되지 않은 부서"):
        books.post(db, a, seed["a"]["mgr"], "2026-05-01",
                  [L("103", 1000, dept="없는부서"), L("401", cr=1000)], "매출", "manual")


def test_payroll_slip_dept(db, seed):
    a = seed["a"]["company"]
    _dept(db, a, "001", "영업팀")
    emp_id = db.execute(
        "INSERT INTO employees (name, dept, company_id) VALUES ('홍길동','영업팀',?)", (a,)
    ).lastrowid
    db.commit()
    ps = {"id": 7, "employee_id": emp_id, "pay_year": 2026, "pay_month": 9, "pay_date": "2026-09-25",
         "gross_pay": 3000000, "net_pay": 2700000, "income_tax": 100000, "resident_tax": 10000,
         "national_pension": 100000, "health_insurance": 60000, "long_care": 8000, "employment_insurance": 22000,
         "employer_pension": 100000, "employer_health": 60000, "employer_employment": 22000, "employer_accident": 5000}
    doc_id = _create_payroll_slip(db, a, ps, "홍길동", seed["a"]["mgr"])
    row = db.execute("SELECT dept FROM slip_lines WHERE doc_id=? AND account_code='801'", (doc_id,)).fetchone()
    assert row["dept"] == "영업팀"


def test_dept_pnl_matches_income_statement(db, seed):
    a = seed["a"]["company"]
    uid = seed["a"]["mgr"]
    _dept(db, a, "001", "A팀")
    _dept(db, a, "002", "B팀")
    books.post(db, a, uid, "2026-03-01",
              [L("101", 1000000), L("401", cr=1000000, dept="A팀")], "매출", "manual")
    books.post(db, a, uid, "2026-03-05",
              [L("813", 500000, dept="B팀"), L("103", cr=500000)], "통신비", "manual")
    db.commit()

    date_from, date_to = _dept_pnl_period(2026, 0)
    rows, totals = _dept_pnl_data(db, a, date_from, date_to)
    _, _, _, i_totals = _income_statement_data(db, a, date_from, date_to)
    assert totals["income"] == i_totals["net_income"]
    by_dept = {r["dept"]: r for r in rows}
    assert by_dept["A팀"]["revenue"] == 1000000
    assert by_dept["B팀"]["expense"] == 500000


def test_fa_disposal_gain(db, seed, login):
    a = seed["a"]["company"]
    fa_id = _asset(db, a)
    _prior_depr(db, a, fa_id, (2024, 2025), 2_400_000)
    c = login("a_mgr")
    tok = csrf(c, f"/fa/{fa_id}/disposal")
    form = {"csrf_token": tok, "disposed_date": "2026-06-01", "supply_amt": "7,000,000", "vat_amt": "0",
           "deposit_code": "103", "partner_id": "", "summary": ""}
    r = c.post(f"/fa/{fa_id}/disposal", data=form, follow_redirects=False)
    assert r.status_code == 303

    doc = db.execute("SELECT * FROM erp_docs WHERE source_type='fa_disposal' AND source_id=?", (fa_id,)).fetchone()
    lines = {(l["account_code"], l["debit"], l["credit"]) for l in
            db.execute("SELECT * FROM slip_lines WHERE doc_id=?", (doc["id"],))}
    assert ("816", 1_199_900, 0) in lines
    assert ("211", 4_800_000, 0) in lines
    assert ("103", 7_000_000, 0) in lines
    assert ("206", 0, 12_000_000) in lines
    assert ("914", 0, 999_900) in lines
    s = db.execute("SELECT SUM(debit), SUM(credit) FROM slip_lines WHERE doc_id=?", (doc["id"],)).fetchone()
    assert s[0] == s[1]
    assert db.execute("SELECT amount FROM fa_depr WHERE asset_id=? AND year=2026", (fa_id,)).fetchone()[0] == 1_199_900
    fa = db.execute("SELECT status, disposed_date FROM fixed_assets WHERE id=?", (fa_id,)).fetchone()
    assert (fa["status"], fa["disposed_date"]) == ("disposed", "2026-06-01")


def test_fa_disposal_loss(db, seed, login):
    a = seed["a"]["company"]
    fa_id = _asset(db, a, code="00002")
    _prior_depr(db, a, fa_id, (2024, 2025), 2_400_000)
    c = login("a_mgr")
    tok = csrf(c, f"/fa/{fa_id}/disposal")
    form = {"csrf_token": tok, "disposed_date": "2026-06-01", "supply_amt": "5,000,000", "vat_amt": "0",
           "deposit_code": "103", "partner_id": "", "summary": ""}
    r = c.post(f"/fa/{fa_id}/disposal", data=form, follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT * FROM erp_docs WHERE source_type='fa_disposal' AND source_id=?", (fa_id,)).fetchone()
    lines = {(l["account_code"], l["debit"], l["credit"]) for l in
            db.execute("SELECT * FROM slip_lines WHERE doc_id=?", (doc["id"],))}
    assert ("970", 1_000_100, 0) in lines
    assert not any(code == "914" for code, _, _ in lines)


def test_fa_disposal_blocks_gap_year(db, seed, login):
    a = seed["a"]["company"]
    fa_id = _asset(db, a, code="00003")
    c = login("a_mgr")
    tok = csrf(c, f"/fa/{fa_id}/disposal")
    form = {"csrf_token": tok, "disposed_date": "2026-06-01", "supply_amt": "5,000,000", "vat_amt": "0",
           "deposit_code": "103", "partner_id": "", "summary": ""}
    r = c.post(f"/fa/{fa_id}/disposal", data=form)
    assert r.status_code == 400
    assert "상각 미반영" in r.json()["error"]


def test_fa_disposal_other_book_404(db, seed, login):
    b = seed["b"]["company"]
    fa_id = _asset(db, b, code="00004")
    c = login("a_mgr")
    r = c.get(f"/fa/{fa_id}/disposal")
    assert r.status_code == 404


def test_fa_scrap_without_proceeds(db, seed, login):
    a = seed["a"]["company"]
    fa_id = _asset(db, a, code="00005")
    _prior_depr(db, a, fa_id, (2024, 2025), 2_400_000)
    c = login("a_mgr")
    tok = csrf(c, f"/fa/{fa_id}/disposal")
    form = {"csrf_token": tok, "disposed_date": "2026-06-01", "supply_amt": "0", "vat_amt": "0",
           "deposit_code": "", "partner_id": "", "summary": ""}
    r = c.post(f"/fa/{fa_id}/disposal", data=form, follow_redirects=False)
    assert r.status_code == 303
    doc = db.execute("SELECT id FROM erp_docs WHERE source_type='fa_disposal' AND source_id=?", (fa_id,)).fetchone()
    lines = {(l["account_code"], l["debit"], l["credit"]) for l in
            db.execute("SELECT * FROM slip_lines WHERE doc_id=?", (doc["id"],))}
    assert ("970", 6_000_100, 0) in lines
    assert not any(code == "103" for code, _, _ in lines)


def test_dept_rename_blocked_when_used(db, seed, login):
    a = seed["a"]["company"]
    _dept(db, a, "001", "총무팀")
    books.post(db, a, seed["a"]["mgr"], "2026-05-01",
               [L("801", 100, dept="총무팀"), L("103", cr=100)], "테스트", "manual")
    db.commit()
    did = db.execute("SELECT id FROM depts WHERE company_id=? AND name='총무팀'", (a,)).fetchone()["id"]
    c = login("a_mgr")
    tok = csrf(c, "/depts")
    r = c.post("/depts/save", data={"csrf_token": tok, "dept_id": str(did), "name": "경영지원팀",
                                    "sort": "0", "is_active": "1"})
    assert r.status_code == 400
    assert db.execute("SELECT name FROM depts WHERE id=?", (did,)).fetchone()["name"] == "총무팀"
