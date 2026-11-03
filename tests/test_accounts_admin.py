from core import books
from tests.conftest import csrf


def test_inactive_blocked_balance(db, seed, login):
    a = seed["a"]["company"]
    wk = seed["a"]["wk"]
    m = login("a_mgr")
    tok = csrf(m, "/fi/accounts")

    books.post(db, a, wk, "2026-05-01",
               [{"code": "103", "debit": 100_000, "credit": 0},
                {"code": "401", "debit": 0, "credit": 100_000}],
               "매출", "manual")
    db.commit()

    r = m.post("/fi/accounts/103", data={
        "csrf_token": tok, "name": "현금", "is_active": "0", "req_partner": "0", "req_dept": "0",
    })
    assert r.status_code == 400
    assert r.json()["error"] == "잔액이 남아 있는 계정은 사용중지할 수 없습니다."
    assert db.execute("SELECT is_active FROM accounts WHERE company_id=? AND code='103'", (a,)).fetchone()[0] == 1

    books.post(db, a, wk, "2026-05-02",
               [{"code": "401", "debit": 100_000, "credit": 0},
                {"code": "103", "debit": 0, "credit": 100_000}],
               "매출 취소", "manual")
    db.commit()

    r2 = m.post("/fi/accounts/103", data={
        "csrf_token": tok, "name": "현금", "is_active": "0", "req_partner": "0", "req_dept": "0",
    }, follow_redirects=False)
    assert r2.status_code == 303
    assert db.execute("SELECT is_active FROM accounts WHERE company_id=? AND code='103'", (a,)).fetchone()[0] == 0


def test_add_and_toggle(db, seed, login):
    m = login("a_mgr")
    tok = csrf(m, "/fi/accounts")
    r = m.post("/fi/accounts", data={"csrf_token": tok, "code": "825", "name": "교육비", "category": "비용"}, follow_redirects=False)
    assert r.status_code == 303
    a = seed["a"]["company"]
    assert db.execute("SELECT is_debit FROM accounts WHERE company_id=? AND code='825'", (a,)).fetchone()[0] == 1
    assert not db.execute("SELECT 1 FROM accounts WHERE company_id=? AND code='825'", (seed["b"]["company"],)).fetchone()
    dup = m.post("/fi/accounts", data={"csrf_token": tok, "code": "825", "name": "중복", "category": "비용"})
    assert dup.status_code == 400
    assert dup.json()["error"] == "이미 존재하는 계정코드입니다."
    bad_cat = m.post("/fi/accounts", data={"csrf_token": tok, "code": "826", "name": "틀림", "category": "자산"})
    assert bad_cat.status_code == 400
    assert bad_cat.json()["error"] == "계정코드와 계정구분이 맞지 않습니다."
    m.post("/fi/accounts/825", data={"csrf_token": tok, "name": "교육비", "is_active": "0", "req_partner": "0", "req_dept": "1"}, follow_redirects=False)
    row = db.execute("SELECT is_active, req_dept FROM accounts WHERE company_id=? AND code='825'", (a,)).fetchone()
    assert tuple(row) == (0, 1)


def test_worker_readonly(db, seed, login):
    w = login("a_wk")
    assert w.get("/fi/accounts").status_code == 200
    r = w.post("/fi/accounts", data={"csrf_token": csrf(w, "/fi/accounts"), "code": "825", "name": "x", "category": "비용"})
    assert r.status_code == 403
    assert r.json()["error"] == "계정과목 등록 권한이 없습니다."


def test_edit_not_found(db, seed, login):
    m = login("a_mgr")
    tok = csrf(m, "/fi/accounts")
    r = m.post("/fi/accounts/999", data={"csrf_token": tok, "name": "x", "is_active": "1", "req_partner": "0", "req_dept": "0"})
    assert r.status_code == 404
    assert r.json()["error"] == "계정을 찾을 수 없습니다."
