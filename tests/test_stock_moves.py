from tests.conftest import csrf
from core import stock


def _setup(db, cid, code="1"):
    item = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES (?,'품목',?)", (f"I{code}", cid)
    ).lastrowid
    w1 = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES (?,'본창고',?)", (f"W{code}", cid)).lastrowid
    w2 = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES (?,'2창고',?)", (f"X{code}", cid)).lastrowid
    return item, w1, w2


def _gl(db, cid, code):
    return db.execute(
        """SELECT COALESCE(SUM(sl.debit - sl.credit), 0) FROM slip_lines sl JOIN erp_docs d ON d.id=sl.doc_id
           WHERE d.company_id=? AND d.status='done' AND sl.account_code=?""",
        (cid, code),
    ).fetchone()[0]


def test_opening_then_count_loss(db, seed, login):
    a = seed["a"]["company"]
    item, w1, _ = _setup(db, a)
    db.commit()
    c = login("a_mgr")
    r = c.post("/stock/adjustments", data={
        "csrf_token": csrf(c, f"/stock/adjustments/new?wh={w1}"), "warehouse_id": str(w1),
        "move_date": "2026-09-01", "reason": "기초재고", f"count_{item}": "10", f"price_{item}": "1,000",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT stock_amt FROM items WHERE id=?", (item,)).fetchone()[0] == 10000
    assert db.execute("SELECT doc_id FROM stock_moves").fetchone()[0] is None

    r = c.post("/stock/adjustments", data={
        "csrf_token": csrf(c, f"/stock/adjustments/new?wh={w1}"), "warehouse_id": str(w1),
        "move_date": "2026-09-30", "reason": "실사조정", f"count_{item}": "8",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT quantity FROM stock WHERE item_id=?", (item,)).fetchone()[0] == 8
    assert _gl(db, a, "451") == 2000 and _gl(db, a, "120") == -2000
    assert c.get(r.headers["location"]).status_code == 200


def test_count_rejects_bad_input(db, seed, login):
    a = seed["a"]["company"]
    item, w1, _ = _setup(db, a)
    db.commit()
    c = login("a_mgr")
    tok = csrf(c, f"/stock/adjustments/new?wh={w1}")
    for val in ("-1", "abc"):
        r = c.post("/stock/adjustments", data={
            "csrf_token": tok, "warehouse_id": str(w1), "move_date": "2026-09-01", f"count_{item}": val,
        }, follow_redirects=False)
        assert r.status_code == 400
    r = c.post("/stock/adjustments", data={"csrf_token": tok, "warehouse_id": str(w1)}, follow_redirects=False)
    assert r.status_code == 400 and "바뀐 품목" in r.json()["error"]


def test_transfer_keeps_value(db, seed, login):
    a = seed["a"]["company"]
    item, w1, w2 = _setup(db, a)
    stock.move_in(db, item, w1, 3, "2026-09-01", "gr", 1, seed["a"]["wk"], 1000)
    stock.move_in(db, item, w1, 3, "2026-09-01", "gr", 2, seed["a"]["wk"], 1001)
    db.commit()
    c = login("a_mgr")
    tok = csrf(c, f"/stock/transfers/new?wh={w1}")
    r = c.post("/stock/transfers", data={
        "csrf_token": tok, "warehouse_id": str(w1), "to_wh_id": str(w2), "move_date": "2026-09-05",
        f"qty_{item}": "4",
    }, follow_redirects=False)
    assert r.status_code == 303
    q = dict(db.execute("SELECT warehouse_id, quantity FROM stock WHERE item_id=?", (item,)).fetchall())
    assert q == {w1: 2, w2: 4}
    assert db.execute("SELECT stock_amt FROM items WHERE id=?", (item,)).fetchone()[0] == 6003

    r = c.post("/stock/transfers", data={
        "csrf_token": tok, "warehouse_id": str(w1), "to_wh_id": str(w2), "move_date": "2026-09-05",
        f"qty_{item}": "5",
    }, follow_redirects=False)
    assert r.status_code == 400 and "재고 부족" in r.json()["error"]
    r = c.post("/stock/transfers", data={
        "csrf_token": tok, "warehouse_id": str(w1), "to_wh_id": str(w1), f"qty_{item}": "1",
    }, follow_redirects=False)
    assert r.status_code == 400


def test_moves_tenant(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    item_b, wb, _ = _setup(db, b, "2")
    move_b = db.execute(
        """INSERT INTO stock_moves (company_id, kind, move_number, move_date, warehouse_id)
           VALUES (?,'adjust','ADJ-2026-0001','2026-09-01',?)""",
        (b, wb),
    ).lastrowid
    db.commit()
    c = login("a_mgr")
    r = c.get(f"/stock/adjustments/{move_b}", follow_redirects=False)
    assert r.status_code == 303
    assert "ADJ-2026-0001" not in c.get("/stock/adjustments").text
    r = c.post("/stock/adjustments", data={
        "csrf_token": csrf(c, "/stock/adjustments/new"), "warehouse_id": str(wb), f"count_{item_b}": "5",
    }, follow_redirects=False)
    assert r.status_code == 400
    assert db.execute("SELECT COUNT(*) FROM stock WHERE item_id=?", (item_b,)).fetchone()[0] == 0


def test_closed_period_blocks_adjust(db, seed, login):
    a = seed["a"]["company"]
    item, w1, _ = _setup(db, a)
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,9,'closed')", (a,))
    db.commit()
    c = login("a_mgr")
    r = c.post("/stock/adjustments", data={
        "csrf_token": csrf(c, f"/stock/adjustments/new?wh={w1}"), "warehouse_id": str(w1),
        "move_date": "2026-09-10", f"count_{item}": "3",
    }, follow_redirects=False)
    assert r.status_code == 400 and "마감" in r.json()["error"]



def test_ledger_bad_param_no_json(login):
    c = login("a_mgr")
    assert c.get("/stock/ledger?wh=0").status_code == 200
    r = c.get("/stock/ledger?wh=")
    assert r.status_code == 400
    assert "int_parsing" not in r.text
