import pytest

from core import books, invoices

PATHS = ["/ledger/purchase", "/ledger/sales", "/ledger/ar-ap", "/ledger/pnl",
         "/ledger/general?account_code=813", "/ledger/trial-balance", "/tax-invoices",
         "/report/income-statement", "/report/balance-sheet", "/report/cash-flow", "/ledger/aging"]


@pytest.fixture
def two_books(db, seed):
    for key, amt in (("a", 111111), ("b", 999999)):
        books.post(db, seed[key]["company"], seed[key]["wk"], "2026-09-10",
                   [{"code": "813", "debit": amt, "credit": 0}, {"code": "103", "debit": 0, "credit": amt}],
                   f"{key}사 통신비", "manual")
    db.commit()


@pytest.mark.parametrize("path", PATHS)
def test_report_shows_only_own_book(two_books, login, path):
    html = login("a_mgr").get(path + ("&" if "?" in path else "?") + "year=2026&date_from=2026-01-01&date_to=2026-12-31").text
    assert "999,999" not in html


def test_ar_ap_filters_by_partner(db, seed, login):
    a = seed["a"]["company"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','거래처P',?)", (a,)).lastrowid
    books.post(db, a, seed["a"]["wk"], "2026-09-10",
               [{"code": "110", "debit": 123456, "credit": 0, "partner_id": pid},
                {"code": "401", "debit": 0, "credit": 123456}],
               "매출전표", "manual")
    db.commit()
    html = login("a_mgr").get(f"/ledger/ar-ap?partner=거래처P&date_from=2026-01-01&date_to=2026-12-31").text
    assert "123,456" in html


def test_balance_sheet_excludes_other_book(db, seed, login):
    for key, amt in (("a", 222222), ("b", 777777)):
        books.post(db, seed[key]["company"], seed[key]["wk"], "2026-09-10",
                   [{"code": "103", "debit": amt, "credit": 0}, {"code": "331", "debit": 0, "credit": amt}],
                   f"{key}사 자본금", "manual")
    db.commit()
    html = login("a_mgr").get("/report/balance-sheet?as_of=2026-12-31").text
    assert "222,222" in html
    assert "777,777" not in html


def test_reports_skip_unposted(db, seed, login):
    a = seed["a"]["company"]
    doc_id = books.post(db, a, seed["a"]["wk"], "2026-09-10",
                        [{"code": "813", "debit": 555555, "credit": 0}, {"code": "103", "debit": 0, "credit": 555555}],
                        "대기 전표", "manual")
    db.execute("UPDATE erp_docs SET status='wait' WHERE id=?", (doc_id,))
    db.commit()
    c = login("a_mgr")
    for path in ("/ledger/trial-balance?date_from=2026-01-01&date_to=2026-12-31",
                 "/ledger/general?account_code=813&date_from=2026-01-01&date_to=2026-12-31",
                 "/report/balance-sheet?as_of=2026-12-31"):
        assert "555,555" not in c.get(path).text


def test_tax_invoices_include_auto_slips(db, seed, login):
    a = seed["a"]["company"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','가고객',?)", (a,)).lastrowid
    doc = books.post(db, a, seed["a"]["wk"], "2026-09-10",
               [{"code": "110", "debit": 333333, "credit": 0, "partner_id": pid},
                {"code": "401", "debit": 0, "credit": 333333}],
               "매출 전표 (SH-1)", "ship")
    invoices.add(db, a, seed["a"]["wk"], {
        "kind": "매출", "tax_type": "면세", "evidence": "계산서", "issue_date": "2026-09-10",
        "partner_id": pid, "supply_amt": 333333, "vat": 0, "doc_id": doc})
    db.commit()
    assert "333,333" in login("a_mgr").get("/tax-invoices?date_from=2026-09-01&date_to=2026-09-30").text


def test_search_scoped_to_book(db, seed, login):
    for book, uid in ((seed["b"]["company"], seed["b"]["wk"]), (0, seed["staff"])):
        books.post(db, book, uid, "2026-09-10",
                   [{"code": "813", "debit": 1000, "credit": 0}, {"code": "103", "debit": 0, "credit": 1000}],
                   f"비밀통신비{book}", "manual")
        db.execute("INSERT INTO partners (code, name, company_id) VALUES (?,?,?)",
                   (f"P{book}", f"비밀거래처{book}", book))
    db.commit()
    b = seed["b"]["company"]
    labels = " ".join(r["label"] for r in login("t_staff").get("/api/search?q=비밀").json())
    assert "비밀통신비0" in labels and "비밀거래처0" in labels
    assert f"비밀통신비{b}" not in labels and f"비밀거래처{b}" not in labels
