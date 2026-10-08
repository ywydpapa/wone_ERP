import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import seed_accounting as sa

TODAY = datetime.date(2026, 9, 30)


def _acct_balances(conn, book):
    rows = conn.execute(
        """SELECT sl.account_code code, SUM(sl.debit) d, SUM(sl.credit) c
           FROM slip_lines sl JOIN erp_docs d ON d.id=sl.doc_id
           WHERE d.company_id=? AND d.status='done'
           GROUP BY sl.account_code""",
        (book,),
    ).fetchall()
    asset = liab = equity = revenue = expense = 0
    for r in rows:
        acct = conn.execute(
            "SELECT category, is_debit FROM accounts WHERE company_id=? AND code=?", (book, r["code"])
        ).fetchone()
        bal = r["d"] - r["c"] if acct["is_debit"] else r["c"] - r["d"]
        if acct["category"] == "자산":
            asset += bal
        elif acct["category"] == "부채":
            liab += bal
        elif acct["category"] == "자본":
            equity += bal
        elif acct["category"] == "수익":
            revenue += bal
        elif acct["category"] == "비용":
            expense += bal
    return asset, liab, equity, revenue - expense


def _aging_buckets(conn, book, code, sign):
    rows = conn.execute(
        """SELECT sl.debit, sl.credit, d.slip_date FROM slip_lines sl JOIN erp_docs d ON d.id=sl.doc_id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code=? AND sl.partner != ''""",
        (book, code),
    ).fetchall()
    buckets = {"cur": 0, "d30": 0, "d60": 0, "over90": 0}
    for r in rows:
        age = (TODAY - datetime.date.fromisoformat(r["slip_date"])).days
        amt = (r["debit"] - r["credit"]) * sign
        key = "cur" if age <= 30 else "d30" if age <= 60 else "d60" if age <= 90 else "over90"
        buckets[key] += amt
    return buckets


def test_seed_creates_balanced_books(seed, db):
    book = seed["a"]["company"]
    sa.run(db, book)

    bad = db.execute(
        """SELECT d.id FROM erp_docs d JOIN slip_lines sl ON sl.doc_id=d.id
           WHERE d.company_id=? GROUP BY d.id HAVING SUM(sl.debit) != SUM(sl.credit)""",
        (book,),
    ).fetchall()
    assert bad == []

    tb = db.execute(
        """SELECT COALESCE(SUM(sl.debit),0) d, COALESCE(SUM(sl.credit),0) c
           FROM slip_lines sl JOIN erp_docs d ON d.id=sl.doc_id
           WHERE d.company_id=? AND d.status='done'""",
        (book,),
    ).fetchone()
    assert tb["d"] == tb["c"]
    assert tb["d"] > 0

    asset, liab, equity, net_income = _acct_balances(db, book)
    assert asset == liab + equity + net_income
    assert net_income != 0

    ar = _aging_buckets(db, book, "110", 1)
    ap = _aging_buckets(db, book, "251", -1)
    assert sum(1 for v in ar.values() if v != 0) >= 3
    assert sum(1 for v in ap.values() if v != 0) >= 3

    sales_partners = db.execute(
        "SELECT COUNT(DISTINCT partner_id) c FROM tax_invoices WHERE company_id=? AND kind='매출'", (book,)
    ).fetchone()["c"]
    buy_partners = db.execute(
        "SELECT COUNT(DISTINCT partner_id) c FROM tax_invoices WHERE company_id=? AND kind='매입'", (book,)
    ).fetchone()["c"]
    assert sales_partners > 0
    assert buy_partners > 0

    closings = {(r["year"], r["month"]) for r in db.execute(
        "SELECT year, month FROM fi_closings WHERE company_id=? AND status='closed'", (book,)
    )}
    assert (2026, 7) in closings
    assert (2026, 8) in closings

    statuses = {r["status"] for r in db.execute(
        "SELECT DISTINCT status FROM erp_docs WHERE company_id=? AND source_type='seed'", (book,)
    )}
    assert {"draft", "wait", "rejected"} <= statuses


def test_seed_untouches_other_companies(seed, db):
    book_a = seed["a"]["company"]
    book_b = seed["b"]["company"]

    docs_b_before = db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=?", (book_b,)).fetchone()["c"]
    docs_0_before = db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=0").fetchone()["c"]

    sa.run(db, book_a)

    docs_b_after = db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=?", (book_b,)).fetchone()["c"]
    docs_0_after = db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=0").fetchone()["c"]
    partners_b = db.execute("SELECT COUNT(*) c FROM partners WHERE company_id=?", (book_b,)).fetchone()["c"]

    assert docs_b_after == docs_b_before
    assert docs_0_after == docs_0_before
    assert partners_b == 0


def test_seed_is_idempotent(seed, db):
    book = seed["a"]["company"]
    sa.run(db, book)
    first = db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=?", (book,)).fetchone()["c"]
    first_partners = db.execute("SELECT COUNT(*) c FROM partners WHERE company_id=?", (book,)).fetchone()["c"]
    first_inv = db.execute("SELECT COUNT(*) c FROM tax_invoices WHERE company_id=?", (book,)).fetchone()["c"]

    sa.run(db, book)
    second = db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=?", (book,)).fetchone()["c"]
    second_partners = db.execute("SELECT COUNT(*) c FROM partners WHERE company_id=?", (book,)).fetchone()["c"]
    second_inv = db.execute("SELECT COUNT(*) c FROM tax_invoices WHERE company_id=?", (book,)).fetchone()["c"]

    assert first == second
    assert first_partners == second_partners
    assert first_inv == second_inv
