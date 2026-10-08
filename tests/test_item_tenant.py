import sqlite3

import pytest

from migrate import run_migrations
from tests.conftest import csrf

MARK = "B-ITEM-SECRET"


def test_migration_clones_shared_item_and_remaps_lines(tmp_path):
    path = str(tmp_path / "m.db")
    run_migrations(path, upto=69)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    cA = conn.execute("INSERT INTO client_companies (name) VALUES ('가테스트')").lastrowid
    cB = conn.execute("INSERT INTO client_companies (name) VALUES ('나테스트')").lastrowid
    uid = conn.execute("INSERT INTO users (username, password, name, role) VALUES ('m','x','m','client')").lastrowid
    conn.execute("INSERT INTO client_users (user_id, company_id) VALUES (?,?)", (uid, cA))

    item = conn.execute("INSERT INTO items (item_code, item_name) VALUES ('SHARED','공유품목')").lastrowid
    pidA = conn.execute("INSERT INTO partners (code, name, company_id) VALUES ('PA','a',?)", (cA,)).lastrowid
    pidB = conn.execute("INSERT INTO partners (code, name, company_id) VALUES ('PB','b',?)", (cB,)).lastrowid
    poA1 = conn.execute(
        "INSERT INTO purchase_orders (po_number, partner_id, po_date, company_id) VALUES ('POA1',?,'2026-01-01',?)",
        (pidA, cA),
    ).lastrowid
    poA2 = conn.execute(
        "INSERT INTO purchase_orders (po_number, partner_id, po_date, company_id) VALUES ('POA2',?,'2026-01-01',?)",
        (pidA, cA),
    ).lastrowid
    poB1 = conn.execute(
        "INSERT INTO purchase_orders (po_number, partner_id, po_date, company_id) VALUES ('POB1',?,'2026-01-01',?)",
        (pidB, cB),
    ).lastrowid
    conn.execute("INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,1,100,100)", (poA1, item))
    conn.execute("INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,1,100,100)", (poA2, item))
    conn.execute("INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,1,100,100)", (poB1, item))

    unused = conn.execute("INSERT INTO items (item_code, item_name, created_by) VALUES ('UNUSED','미사용',?)", (uid,)).lastrowid
    orphan = conn.execute("INSERT INTO items (item_code, item_name) VALUES ('ORPHAN','고아품목')").lastrowid

    conn.commit()
    conn.close()

    run_migrations(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    # A가 2건, B가 1건 참조 -> 원본(item)은 A 소유로 유지, B용 clone이 새로 생성
    orig = conn.execute("SELECT company_id FROM items WHERE id=?", (item,)).fetchone()
    assert orig["company_id"] == cA
    clone = conn.execute("SELECT id, company_id FROM items WHERE item_code='SHARED' AND id!=?", (item,)).fetchone()
    assert clone is not None and clone["company_id"] == cB

    line_b = conn.execute("SELECT item_id FROM po_lines WHERE po_id=?", (poB1,)).fetchone()
    assert line_b["item_id"] == clone["id"]
    line_a1 = conn.execute("SELECT item_id FROM po_lines WHERE po_id=?", (poA1,)).fetchone()
    assert line_a1["item_id"] == item

    assert conn.execute("SELECT company_id FROM items WHERE id=?", (unused,)).fetchone()["company_id"] == cA
    assert conn.execute("SELECT company_id FROM items WHERE id=?", (orphan,)).fetchone()["company_id"] == 0
    conn.close()


@pytest.fixture
def ab_items(db, seed):
    a, b = seed["a"]["company"], seed["b"]["company"]
    item_a = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('IA','A품목',?)", (a,)).lastrowid
    item_b = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('IB',?,?)", (MARK, b)).lastrowid
    wh_a = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('WA','A창고',?)", (a,)).lastrowid
    wh_b = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('WB',?,?)", (MARK, b)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,10)", (item_a, wh_a))
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,10)", (item_b, wh_b))
    db.commit()
    return {"a": {"item": item_a, "wh": wh_a}, "b": {"item": item_b, "wh": wh_b}}


def test_item_list_hides_other_company(ab_items, login):
    r = login("a_mgr").get("/items")
    assert r.status_code == 200
    assert MARK not in r.text


def test_item_edit_blocks_other_company(ab_items, login):
    r = login("a_mgr").get(f"/items/{ab_items['b']['item']}/edit", follow_redirects=False)
    assert r.status_code == 303
    assert MARK not in r.text


def test_warehouse_list_hides_other_company(ab_items, login):
    r = login("a_mgr").get("/warehouses")
    assert MARK not in r.text


def test_warehouse_edit_blocks_other_company(ab_items, login):
    r = login("a_mgr").get(f"/warehouses/{ab_items['b']['wh']}/edit", follow_redirects=False)
    assert r.status_code == 303
    assert MARK not in r.text


def test_stock_list_hides_other_company(ab_items, login):
    r = login("a_mgr").get("/stock")
    assert MARK not in r.text


def test_po_line_rejects_other_company_item(db, ab_items, seed, login):
    a = seed["a"]["company"]
    pid = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('PA','a거래처',?,'supplier')", (a,)
    ).lastrowid
    db.commit()

    c = login("a_mgr")
    tok = csrf(c, "/purchase-orders/new")
    before = db.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]
    c.post("/purchase-orders/save", data={
        "csrf_token": tok, "po_id": "0", "partner_id": str(pid), "po_date": "2026-09-20",
        "line_nums": "1", "item_id_1": str(ab_items["b"]["item"]), "qty_1": "1", "price_1": "100",
    }, follow_redirects=False)
    after = db.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]
    assert after == before


def test_same_item_code_allowed_in_two_companies(db, seed):
    a, b = seed["a"]["company"], seed["b"]["company"]
    ia = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('DUP','a품목',?)", (a,)).lastrowid
    ib = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('DUP','b품목',?)", (b,)).lastrowid
    db.commit()
    assert ia != ib
