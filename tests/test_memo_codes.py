from tests.conftest import csrf


def test_memo_code_crud(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    r = c.post("/memo-codes/save", data={
        "csrf_token": csrf(c, "/memo-codes/new"),
        "code": "101", "text": "현금 입금", "account_code": "101",
    }, follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT * FROM memo_codes WHERE company_id=?", (a,)).fetchone()
    assert row["code"] == "101" and row["text"] == "현금 입금"

    html = c.get("/memo-codes").text
    assert "현금 입금" in html

    r = c.post("/memo-codes/save", data={
        "csrf_token": csrf(c, "/memo-codes/new"),
        "memo_id": str(row["id"]),
        "code": "101", "text": "현금 입금 수정", "account_code": "101",
        "is_active": "0",
    }, follow_redirects=False)
    assert r.status_code == 303
    updated = db.execute("SELECT text, is_active FROM memo_codes WHERE id=?", (row["id"],)).fetchone()
    assert updated["text"] == "현금 입금 수정" and updated["is_active"] == 0


def test_memo_code_scoped_by_company(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO memo_codes (company_id, code, text) VALUES (?,?,?)", (b, "900", "B사 적요"))
    db.commit()
    c = login("a_wk")
    html = c.get("/memo-codes").text
    assert "B사 적요" not in html

    row = db.execute("SELECT id FROM memo_codes WHERE company_id=?", (b,)).fetchone()
    r = c.get(f"/memo-codes/{row['id']}/edit", follow_redirects=False)
    assert r.status_code == 303


def test_memo_code_api_scoped(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO memo_codes (company_id, code, text) VALUES (?,?,?)", (a, "101", "A사 적요"))
    db.execute("INSERT INTO memo_codes (company_id, code, text) VALUES (?,?,?)", (b, "101", "B사 적요"))
    db.commit()
    c = login("a_wk")
    rows = c.get("/api/memo_codes").json()
    texts = [r["name"] for r in rows]
    assert "A사 적요" in texts and "B사 적요" not in texts


def test_partner_auto_code(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_wk")
    r = c.post("/partners/save", data={
        "csrf_token": csrf(c, "/partners/new"),
        "name": "자동코드거래처",
    }, follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT * FROM partners WHERE company_id=? AND name=?", (a, "자동코드거래처")).fetchone()
    assert row["code"] == "00001"

    r = c.post("/partners/save", data={
        "csrf_token": csrf(c, "/partners/new"),
        "name": "자동코드거래처2",
    }, follow_redirects=False)
    assert r.status_code == 303
    row2 = db.execute("SELECT * FROM partners WHERE company_id=? AND name=?", (a, "자동코드거래처2")).fetchone()
    assert row2["code"] == "00002"

    r = c.post("/partners/save", data={
        "csrf_token": csrf(c, "/partners/new"),
        "name": "수동코드거래처", "code": "VIP01",
    }, follow_redirects=False)
    assert r.status_code == 303
    row3 = db.execute("SELECT * FROM partners WHERE company_id=? AND name=?", (a, "수동코드거래처")).fetchone()
    assert row3["code"] == "VIP01"
