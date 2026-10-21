from core import books
from tests.conftest import csrf


def _dept(db, book, code, name):
    db.execute("INSERT INTO depts (company_id, code, name) VALUES (?,?,?)", (book, code, name))
    db.commit()


def test_budget_save_with_dept(db, seed, login):
    a = seed["a"]["company"]
    _dept(db, a, "001", "영업팀")

    c = login("a_mgr")
    tok = csrf(c, "/budget/edit")
    c.post("/budget/save", data={
        "csrf_token": tok, "year": "2026", "dept": "영업팀", "b_813_1": "100000",
    }, follow_redirects=False)

    row = db.execute(
        "SELECT amount, dept, company_id FROM budgets WHERE account_code='813' AND year=2026 AND month=1"
    ).fetchone()
    assert row["dept"] == "영업팀"
    assert row["amount"] == 100000
    assert row["company_id"] == a


def test_budget_dept_and_company_wide_are_independent(db, seed, login):
    a = seed["a"]["company"]
    _dept(db, a, "001", "영업팀")

    c = login("a_mgr")
    tok = csrf(c, "/budget/edit")
    c.post("/budget/save", data={"csrf_token": tok, "year": "2026", "dept": "", "b_813_1": "50000"})
    tok = csrf(c, "/budget/edit")
    c.post("/budget/save", data={"csrf_token": tok, "year": "2026", "dept": "영업팀", "b_813_1": "70000"})

    rows = db.execute(
        "SELECT dept, amount FROM budgets WHERE account_code='813' AND year=2026 AND month=1 ORDER BY dept"
    ).fetchall()
    assert len(rows) == 2
    by_dept = {r["dept"]: r["amount"] for r in rows}
    assert by_dept[""] == 50000
    assert by_dept["영업팀"] == 70000


def test_budget_edit_shows_dept_select(db, seed, login):
    a = seed["a"]["company"]
    _dept(db, a, "001", "영업팀")
    db.commit()

    html = login("a_mgr").get("/budget/edit").text
    assert "영업팀" in html
    assert "전사" in html


def test_vs_actual_company_wide_matches_all_depts(db, seed, login):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    _dept(db, a, "001", "영업팀")
    db.execute(
        "INSERT INTO budgets (company_id, dept, account_code, year, month, amount) VALUES (?,'',?,2026,9,500000)",
        (a, "813"),
    )
    books.post(db, a, wk, "2026-09-05",
               [{"code": "813", "debit": 300000, "credit": 0, "dept": "영업팀"},
                {"code": "103", "debit": 0, "credit": 300000}],
               "통신비", "manual")
    db.commit()

    html = login("a_mgr").get("/budget/vs-actual?year=2026&month=9").text
    assert "300,000" in html


def test_vs_actual_dept_filter_isolates_that_dept(db, seed, login):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    _dept(db, a, "001", "영업팀")
    _dept(db, a, "002", "관리팀")
    db.execute(
        "INSERT INTO budgets (company_id, dept, account_code, year, month, amount) VALUES (?,'영업팀',?,2026,9,200000)",
        (a, "813"),
    )
    books.post(db, a, wk, "2026-09-05",
               [{"code": "813", "debit": 300000, "credit": 0, "dept": "영업팀"},
                {"code": "103", "debit": 0, "credit": 300000}],
               "영업팀 통신비", "manual")
    books.post(db, a, wk, "2026-09-06",
               [{"code": "813", "debit": 900000, "credit": 0, "dept": "관리팀"},
                {"code": "103", "debit": 0, "credit": 900000}],
               "관리팀 통신비", "manual")
    db.commit()

    html = login("a_mgr").get("/budget/vs-actual?year=2026&month=9&dept=영업팀").text
    assert "300,000" in html
    assert "900,000" not in html
