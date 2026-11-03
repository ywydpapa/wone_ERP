import pytest

from core import equity, books
from core.books import balance_sheet_data as _balance_sheet_data
from routers.erp_equity import _equity_changes_data


def lines_of(db, doc_id):
    return [(r["account_code"], r["debit"], r["credit"]) for r in db.execute(
        "SELECT account_code, debit, credit FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]


def test_approve_lines(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    rid = equity.approve(db, book, uid, 2025, "2026-03-20", 100000, 900000, 50000)
    r = db.execute("SELECT * FROM re_appropriations WHERE id=?", (rid,)).fetchone()
    assert r["doc_id"]
    assert lines_of(db, r["doc_id"]) == [("375", 1050000, 0), ("351", 0, 100000), ("265", 0, 900000), ("356", 0, 50000)]
    doc = db.execute("SELECT source_type, slip_date FROM erp_docs WHERE id=?", (r["doc_id"],)).fetchone()
    assert doc["source_type"] == "re_approp" and doc["slip_date"] == "2026-03-20"


def test_approve_duplicate_year_rejected(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    equity.approve(db, book, uid, 2025, "2026-03-20", 0, 100000, 0)
    with pytest.raises(ValueError, match="이미 처분"):
        equity.approve(db, book, uid, 2025, "2026-03-21", 0, 50000, 0)


def test_cancel_reapprove(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    rid = equity.approve(db, book, uid, 2025, "2026-03-20", 10000, 90000, 0)
    doc_id = db.execute("SELECT doc_id FROM re_appropriations WHERE id=?", (rid,)).fetchone()["doc_id"]
    equity.cancel(db, book, uid, 2025, "2026-03-25")
    assert equity.get_approp(db, book, 2025) is None
    rev = db.execute("SELECT * FROM erp_docs WHERE reversal_of=?", (doc_id,)).fetchone()
    assert rev["slip_date"] == "2026-03-25"
    # 삭제됐으므로 재확정 가능
    equity.approve(db, book, uid, 2025, "2026-03-26", 10000, 90000, 0)


def test_cancel_missing_raises(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    with pytest.raises(LookupError):
        equity.cancel(db, book, uid, 2025, "2026-03-25")


def test_458_warn_tenth(db, seed):
    book = seed["a"]["company"]
    warn = equity.reserve_warn(db, book, 2026, 5000, 100000)
    assert warn and "상법 458조" in warn


def test_458_skip_half_capital(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]
    books.post(db, book, uid, "2026-01-01",
               [{"code": "103", "debit": 100000, "credit": 0}, {"code": "331", "debit": 0, "credit": 100000}],
               "자본금", "manual")
    books.post(db, book, uid, "2026-01-02",
               [{"code": "103", "debit": 50000, "credit": 0}, {"code": "351", "debit": 0, "credit": 50000}],
               "이익준비금 적립", "manual")
    db.commit()
    warn = equity.reserve_warn(db, book, 2026, 0, 100000)
    assert warn is None


def test_458_no_dividend(db, seed):
    book = seed["a"]["company"]
    assert equity.reserve_warn(db, book, 2026, 0, 0) is None


def test_equity_end_eq_bs(db, seed):
    book, uid = seed["a"]["company"], seed["a"]["mgr"]

    books.post(db, book, uid, "2026-01-05",
               [{"code": "103", "debit": 2000000, "credit": 0}, {"code": "331", "debit": 0, "credit": 2000000}],
               "유상증자", "manual")
    books.post(db, book, uid, "2026-03-01",
               [{"code": "103", "debit": 500000, "credit": 0}, {"code": "401", "debit": 0, "credit": 500000}],
               "매출", "manual")
    books.post(db, book, uid, "2026-03-05",
               [{"code": "813", "debit": 100000, "credit": 0}, {"code": "103", "debit": 0, "credit": 100000}],
               "통신비", "manual")
    db.commit()
    equity.approve(db, book, uid, 2025, "2026-03-20", 10000, 90000, 0)
    db.commit()

    rows, cols = _equity_changes_data(db, book, 2026)
    _, _, _, _, _, _, equity_total = _balance_sheet_data(db, book, "2026-12-31")
    ending = next(r for r in rows if r["label"] == "기말")
    assert ending["total"] == equity_total


def test_is_compare(db, seed, login):
    book, wk = seed["a"]["company"], seed["a"]["wk"]
    books.post(db, book, wk, "2025-03-01",
               [{"code": "103", "debit": 300000, "credit": 0}, {"code": "401", "debit": 0, "credit": 300000}],
               "2025년 매출", "manual")
    books.post(db, book, wk, "2026-03-01",
               [{"code": "103", "debit": 500000, "credit": 0}, {"code": "401", "debit": 0, "credit": 500000}],
               "2026년 매출", "manual")
    db.commit()

    html = login("a_mgr").get(
        "/report/income-statement?date_from=2026-01-01&date_to=2026-12-31&compare=1"
    ).text
    assert "500,000" in html and "300,000" in html and "200,000" in html


def test_bs_compare(db, seed, login):
    book, wk = seed["a"]["company"], seed["a"]["wk"]
    books.post(db, book, wk, "2025-06-01",
               [{"code": "103", "debit": 400000, "credit": 0}, {"code": "331", "debit": 0, "credit": 400000}],
               "2025년 자본금", "manual")
    books.post(db, book, wk, "2026-06-01",
               [{"code": "103", "debit": 600000, "credit": 0}, {"code": "331", "debit": 0, "credit": 600000}],
               "2026년 증자", "manual")
    db.commit()

    html = login("a_mgr").get("/report/balance-sheet?as_of=2026-12-31&compare=1").text
    assert "1,000,000" in html and "400,000" in html and "600,000" in html


def test_balance_sheet_no_compare_unchanged(db, seed, login):
    html = login("a_mgr").get("/report/balance-sheet?as_of=2026-12-31").text
    assert "bs-amounts" not in html
