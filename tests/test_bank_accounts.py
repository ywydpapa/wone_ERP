from tests.conftest import csrf


def test_bank_account_crud(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    r = c.post("/bank-accounts/save", data={
        "csrf_token": csrf(c, "/bank-accounts/new"),
        "bank": "국민은행", "account_no": "123-456-789", "name": "법인 보통예금", "account_code": "103",
    }, follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT * FROM bank_accounts WHERE company_id=?", (a,)).fetchone()
    assert row["bank"] == "국민은행" and row["account_code"] == "103"

    html = c.get("/bank-accounts").text
    assert "국민은행" in html

    r = c.post("/bank-accounts/save", data={
        "csrf_token": csrf(c, "/bank-accounts/new"),
        "account_id": str(row["id"]),
        "bank": "국민은행", "account_no": "123-456-789", "name": "법인 보통예금", "account_code": "103",
        "is_active": "0",
    }, follow_redirects=False)
    assert r.status_code == 303
    updated = db.execute("SELECT is_active FROM bank_accounts WHERE id=?", (row["id"],)).fetchone()
    assert updated["is_active"] == 0


def test_bank_account_scoped_by_company(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code) VALUES (?,?,?,?,?)",
               (b, "신한은행", "999", "B사계좌", "103"))
    db.commit()
    c = login("a_wk")
    html = c.get("/bank-accounts").text
    assert "신한은행" not in html
