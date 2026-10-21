import pytest

from core import books, invoices
from tests.conftest import csrf
from routers.erp_ledger import _daily_data, _journal_data


@pytest.fixture
def two_books(db, seed):
    for key, amt in (("a", 222222), ("b", 888888)):
        books.post(db, seed[key]["company"], seed[key]["wk"], "2026-09-10",
                   [{"code": "813", "debit": amt, "credit": 0}, {"code": "103", "debit": 0, "credit": amt}],
                   f"{key}사 통신비", "manual")
    db.commit()


@pytest.mark.parametrize("path", [
    "/ledger/daily?mode=month&date_from=2026-09-01&date_to=2026-09-30",
    "/ledger/journal?date_from=2026-09-01&date_to=2026-09-30",
])
def test_ledger_scoped_to_own_book(two_books, login, path):
    html = login("a_mgr").get(path).text
    assert "222,222" in html
    assert "888,888" not in html


def test_cash_ledger_scoped(db, seed, login):
    for key, amt in (("a", 333333), ("b", 777777)):
        books.post(db, seed[key]["company"], seed[key]["wk"], "2026-09-10",
                   [{"code": "101", "debit": amt, "credit": 0}, {"code": "401", "debit": 0, "credit": amt}],
                   f"{key}사 현금매출", "manual")
    db.commit()
    html = login("a_mgr").get("/ledger/cash?date_from=2026-09-01&date_to=2026-09-30").text
    assert "333,333" in html
    assert "777,777" not in html


def test_partner_balance_scoped(db, seed, login):
    for key, amt in (("a", 111222), ("b", 999888)):
        cid = seed[key]["company"]
        pid = db.execute(
            "INSERT INTO partners (code, name, company_id) VALUES (?,?,?)", (f"P{key}", f"{key}거래처", cid)
        ).lastrowid
        books.post(db, cid, seed[key]["wk"], "2026-09-10",
                   [{"code": "110", "debit": amt, "credit": 0, "partner_id": pid}, {"code": "401", "debit": 0, "credit": amt}],
                   f"{key}사 매출", "manual")
    db.commit()
    html = login("a_mgr").get("/ledger/partner-balance?account=110&date_from=2026-09-01&date_to=2026-09-30").text
    assert "111,222" in html
    assert "999,888" not in html


def test_daily_ledger_balances(db, seed):
    a = seed["a"]["company"]
    books.post(db, a, seed["a"]["wk"], "2026-09-10",
               [{"code": "813", "debit": 50000, "credit": 0}, {"code": "103", "debit": 0, "credit": 50000}],
               "통신비", "manual")
    books.post(db, a, seed["a"]["wk"], "2026-09-11",
               [{"code": "101", "debit": 30000, "credit": 0}, {"code": "401", "debit": 0, "credit": 30000}],
               "현금매출", "manual")
    db.commit()
    rows, totals = _daily_data(db, a, "2026-09-01", "2026-09-30")
    assert totals["debit_sum"] == totals["credit_sum"]
    assert totals["cur"] - totals["prev"] == 30000
    row = next(r for r in rows if r["code"] == "401")
    assert row["credit_cash"] == 30000
    assert all(r["code"] != "101" for r in rows)


def test_journal_balances(db, seed):
    a = seed["a"]["company"]
    books.post(db, a, seed["a"]["wk"], "2026-09-10",
               [{"code": "813", "debit": 70000, "credit": 0}, {"code": "103", "debit": 0, "credit": 70000}],
               "통신비", "manual")
    db.commit()
    _, _, rows, total_debit, total_credit = _journal_data(db, a, "2026-09-01", "2026-09-30")
    assert total_debit == total_credit == 70000
    assert len(rows) == 2


def test_excel_endpoints_return_csv(db, seed, login):
    a = seed["a"]["company"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','거래처테스트',?)", (a,)).lastrowid
    books.post(db, a, seed["a"]["wk"], "2026-09-10",
               [{"code": "813", "debit": 10000, "credit": 0}, {"code": "103", "debit": 0, "credit": 10000}],
               "통신비", "manual")
    books.post(db, a, seed["a"]["wk"], "2026-09-11",
               [{"code": "110", "debit": 20000, "credit": 0, "partner_id": pid}, {"code": "401", "debit": 0, "credit": 20000}],
               "매출", "manual")
    db.commit()

    c = login("a_mgr")
    paths = [
        "/ledger/general/excel?account_code=813&date_from=2026-09-01&date_to=2026-09-30",
        "/ledger/trial-balance/excel?date_from=2026-09-01&date_to=2026-09-30",
        "/report/income-statement/excel?date_from=2026-09-01&date_to=2026-09-30",
        "/report/balance-sheet/excel?as_of=2026-09-30",
        "/report/cash-flow/excel?date_from=2026-09-01&date_to=2026-09-30",
        "/ledger/ar-ap/excel?date_from=2026-09-01&date_to=2026-09-30",
        "/ledger/ar-ap/excel?partner=거래처테스트&date_from=2026-09-01&date_to=2026-09-30",
        "/ledger/purchase/excel?date_from=2026-09-01&date_to=2026-09-30",
        "/ledger/sales/excel?date_from=2026-09-01&date_to=2026-09-30",
        "/ledger/daily/excel?mode=month&date_from=2026-09-01&date_to=2026-09-30",
        "/ledger/cash/excel?date_from=2026-09-01&date_to=2026-09-30",
        "/ledger/journal/excel?date_from=2026-09-01&date_to=2026-09-30",
        "/ledger/partner-balance/excel?account=110&date_from=2026-09-01&date_to=2026-09-30",
    ]
    for p in paths:
        r = c.get(p)
        assert r.status_code == 200, p
        assert "csv" in r.headers["content-type"], p


def test_reopen_rejects_wrong_password(db, seed, login):
    a = seed["a"]["company"]
    m = login("a_mgr")
    m.post("/fi/closing/close", data={"csrf_token": csrf(m, "/fi/closing"), "year": "2026", "month": "9"})
    closing = db.execute(
        "SELECT id FROM fi_closings WHERE company_id=? AND year=2026 AND month=9", (a,)
    ).fetchone()

    r = m.post("/fi/closing/reopen", data={
        "csrf_token": csrf(m, "/fi/closing"),
        "closing_id": closing["id"], "reason": "확인용", "password": "wrong",
    }, follow_redirects=False)
    assert "wrong_password" in r.headers["location"]
    assert db.execute("SELECT status FROM fi_closings WHERE id=?", (closing["id"],)).fetchone()["status"] == "closed"

    r2 = m.post("/fi/closing/reopen", data={
        "csrf_token": csrf(m, "/fi/closing"),
        "closing_id": closing["id"], "reason": "확인용", "password": "1234",
    }, follow_redirects=False)
    assert "wrong_password" not in r2.headers["location"]
    assert db.execute("SELECT status FROM fi_closings WHERE id=?", (closing["id"],)).fetchone()["status"] == "open"


def _inv(db, book, uid, kind, day, supply, pid, acct, pay, item="품목A"):
    inv = {"kind": kind, "tax_type": "과세", "evidence": "세금계산서", "issue_date": day,
           "partner_id": pid, "supply_amt": supply, "vat": supply // 10, "deduct": 1}
    doc = books.post(db, book, uid, day, invoices.inv_lines(inv, acct, pay, "t"), "t", "tax")
    return invoices.add(db, book, uid, {**inv, "doc_id": doc}, [{"name": item, "supply_amt": supply}])


def test_vat_book_from_invoices(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('V1','매입처',?)", (a,)).lastrowid
    _inv(db, a, uid, "매입", "2026-08-05", 100000, pid, "120", "251")
    orig = _inv(db, a, uid, "매입", "2026-09-03", 50000, pid, "120", "251")
    # 출고 원가 전표는 매입장 대상 아님
    books.post(db, a, uid, "2026-09-10",
               [{"code": "451", "debit": 30000, "credit": 0}, {"code": "120", "debit": 0, "credit": 30000}],
               "출고 원가", "manual")
    invoices.amend(db, a, uid, orig, "2026-09-20", 0, 4)
    _inv(db, a, uid, "매출", "2026-09-05", 70000, pid, "401", "110")
    db.commit()

    c = login("a_mgr")
    html = c.get("/ledger/purchase?date_from=2026-07-01&date_to=2026-09-30").text
    assert "110,000" in html
    assert "-55,000" in html
    assert "30,000" not in html
    assert "77,000" not in html
    assert "8월 월계" in html and "9월 월계" in html

    csv_text = c.get("/ledger/purchase/excel?date_from=2026-07-01&date_to=2026-09-30").text
    assert csv_text.strip().splitlines()[-1].split(",")[5:8] == ["100000", "10000", "110000"]

    sales = c.get("/ledger/sales?date_from=2026-07-01&date_to=2026-09-30&code=11").text
    assert "77,000" in sales
    assert "110,000" not in sales


def test_tax_invoice_list_sort(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["mgr"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('V2','정렬처',?)", (a,)).lastrowid
    _inv(db, a, uid, "매출", "2026-09-05", 30000, pid, "401", "110")
    _inv(db, a, uid, "매출", "2026-09-06", 90000, pid, "401", "110")
    db.commit()

    c = login("a_mgr")
    base = "/tax-invoices?date_from=2026-09-01&date_to=2026-09-30&sort=total"
    asc = c.get(base + "&dir=asc").text
    desc = c.get(base + "&dir=desc").text
    assert asc.index("33,000") < asc.index("99,000")
    assert desc.index("99,000") < desc.index("33,000")
    assert "sort=total&amp;dir=asc" in desc
    assert c.get("/tax-invoices?sort=1;DROP").status_code == 200
