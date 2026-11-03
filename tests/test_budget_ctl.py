from core import books, budget
from tests.conftest import csrf
from tests.test_slip_routes import _form


def _dept(db, book, code, name):
    db.execute("INSERT INTO depts (company_id, code, name) VALUES (?,?,?)", (book, code, name))
    db.commit()


def _set_budget(db, book, code, amount, dept="", year=2026, month=9):
    db.execute(
        "INSERT INTO budgets (company_id, dept, account_code, year, month, amount) VALUES (?,?,?,?,?,?)",
        (book, dept, code, year, month, amount),
    )
    db.commit()


def _lines_813(amt):
    return [("813", amt, 0, None), ("103", 0, amt, None)]


def test_budget_history(db, seed, login):
    a = seed["a"]["company"]
    _set_budget(db, a, "813", 500000)
    c = login("a_mgr")

    tok = csrf(c, "/budget/vs-actual")
    r = c.post("/budget/change", data={
        "csrf_token": tok, "kind": "추가", "account_code": "813", "dept": "", "year": "2026", "month": "9",
        "amount": "100000", "reason": "증액 필요",
    }, follow_redirects=False)
    assert r.status_code == 303

    tok = csrf(c, "/budget/vs-actual")
    r = c.post("/budget/change", data={
        "csrf_token": tok, "kind": "반환", "account_code": "813", "dept": "", "year": "2026", "month": "9",
        "amount": "50000", "reason": "불필요",
    }, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute(
        "SELECT amount FROM budgets WHERE company_id=? AND dept='' AND account_code='813' AND year=2026 AND month=9", (a,)
    ).fetchone()
    assert row["amount"] == 550000

    hist = db.execute(
        "SELECT kind, amount, reason FROM budget_changes WHERE company_id=? AND account_code='813' AND year=2026 AND month=9 ORDER BY id",
        (a,),
    ).fetchall()
    assert [h["kind"] for h in hist] == ["추가", "반환"]
    assert sum(h["amount"] for h in hist) == 50000
    assert hist[1]["reason"] == "불필요"

    html = c.get("/budget/history?year=2026").text
    assert "추가" in html and "반환" in html and "증액 필요" in html


def test_return_over_avail(db, seed, login):
    a = seed["a"]["company"]
    _set_budget(db, a, "813", 100000)
    c = login("a_mgr")
    tok = csrf(c, "/budget/vs-actual")
    r = c.post("/budget/change", data={
        "csrf_token": tok, "kind": "반환", "account_code": "813", "dept": "", "year": "2026", "month": "9",
        "amount": "200000", "reason": "반환",
    })
    assert r.status_code == 400
    row = db.execute("SELECT amount FROM budgets WHERE account_code='813' AND year=2026 AND month=9").fetchone()
    assert row["amount"] == 100000


def test_slip_save_warn_requires_confirm(db, seed, login):
    a = seed["a"]["company"]
    _set_budget(db, a, "813", 100000)
    before = db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=?", (a,)).fetchone()["c"]
    c = login("a_wk")
    r = c.post("/api/slip", data=_form(csrf(c), _lines_813(90000), seed["a"]["mgr"]))
    assert r.status_code == 409
    assert "confirm" in r.json()
    assert db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=?", (a,)).fetchone()["c"] == before

    r = c.post("/api/slip", data=_form(csrf(c), _lines_813(90000), seed["a"]["mgr"], credit_ok="1"), follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=?", (a,)).fetchone()["c"] == before + 1


def test_slip_save_notify_once(db, seed, login):
    a = seed["a"]["company"]
    _set_budget(db, a, "813", 100000)
    c = login("a_wk")
    c.post("/api/slip", data=_form(csrf(c), _lines_813(95000), seed["a"]["mgr"], credit_ok="1"), follow_redirects=False)

    notif = db.execute("SELECT title FROM notifications").fetchall()
    assert any(n["title"] == "예산 사용률 경고" for n in notif)


def test_budget_notify_crossing_dedup(db, seed):
    a = seed["a"]["company"]
    _set_budget(db, a, "813", 100000)
    info = {"dept": "", "code": "813", "year": 2026, "month": 9, "pct": 96, "cfg": {"notify_pct": 95}}
    budget.notify_crossings(db, a, [info])
    budget.notify_crossings(db, a, [info])
    cnt = db.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"]
    assert cnt == len(books.book_users(db, a))


def test_block_ignores_confirm(db, seed, login):
    a = seed["a"]["company"]
    _set_budget(db, a, "813", 100000)
    before = db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=?", (a,)).fetchone()["c"]
    c = login("a_wk")
    r = c.post("/api/slip", data=_form(csrf(c), _lines_813(100000), seed["a"]["mgr"]))
    assert r.status_code == 400
    assert "notice" in r.json()

    r = c.post("/api/slip", data=_form(csrf(c), _lines_813(100000), seed["a"]["mgr"], credit_ok="1"))
    assert r.status_code == 400
    assert db.execute("SELECT COUNT(*) c FROM erp_docs WHERE company_id=?", (a,)).fetchone()["c"] == before


def test_auto_slip_ignores_budget(db, seed):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    _set_budget(db, a, "813", 100000)
    doc = books.post(db, a, wk, "2026-09-15",
                      [{"code": "813", "debit": 900000, "credit": 0}, {"code": "103", "debit": 0, "credit": 900000}],
                      "자동전표", "payroll")
    db.commit()
    assert db.execute("SELECT status FROM erp_docs WHERE id=?", (doc,)).fetchone()["status"] == "done"


def test_dept_fallback(db, seed, login):
    a = seed["a"]["company"]
    _dept(db, a, "001", "영업팀")
    _set_budget(db, a, "813", 100000)
    c = login("a_wk")
    r = c.post("/api/slip", data=_form(csrf(c), _lines_813(100000), seed["a"]["mgr"], dept_1="영업팀"))
    assert r.status_code == 400
    assert "notice" in r.json()


def test_unbudgeted_account_skips_check(db, seed, login):
    c = login("a_wk")
    lines = [("804", 999999999, 0, None), ("103", 0, 999999999, None)]
    r = c.post("/api/slip", data=_form(csrf(c), lines, seed["a"]["mgr"]), follow_redirects=False)
    assert r.status_code == 303


def test_vs_actual_shows_new_columns(db, seed, login):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    _set_budget(db, a, "813", 500000)
    books.post(db, a, wk, "2026-09-05",
               [{"code": "813", "debit": 300000, "credit": 0}, {"code": "103", "debit": 0, "credit": 300000}],
               "통신비", "manual")
    db.commit()

    html = login("a_mgr").get("/budget/vs-actual?year=2026&month=9&period=month").text
    assert "가용액" in html and "사용률" in html
    assert "300,000" in html
    assert "200,000" in html


def test_budget_change_tenant_isolation(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    _set_budget(db, a, "813", 100000)
    _set_budget(db, b, "813", 100000)
    c = login("a_mgr")
    tok = csrf(c, "/budget/vs-actual")
    c.post("/budget/change", data={
        "csrf_token": tok, "kind": "추가", "account_code": "813", "dept": "", "year": "2026", "month": "9",
        "amount": "50000", "reason": "증액",
    })
    a_amt = db.execute("SELECT amount FROM budgets WHERE company_id=? AND account_code='813' AND year=2026 AND month=9", (a,)).fetchone()["amount"]
    b_amt = db.execute("SELECT amount FROM budgets WHERE company_id=? AND account_code='813' AND year=2026 AND month=9", (b,)).fetchone()["amount"]
    assert a_amt == 150000
    assert b_amt == 100000
