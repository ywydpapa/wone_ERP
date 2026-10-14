import pytest

from migrate import run_migrations

MARK = "B-SECRET"


@pytest.fixture
def docs(db, seed):
    a, b = seed["a"]["company"], seed["b"]["company"]
    item = db.execute("INSERT INTO items (item_code, item_name, company_id) VALUES ('T-1','공용품목',?)", (a,)).lastrowid
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','창고',?)", (a,)).lastrowid
    ids = {"item": item}
    for key, cid in (("a", a), ("b", b)):
        uid = seed[key]["mgr"]
        tag = MARK if key == "b" else "A-OWN"
        sup = db.execute("INSERT INTO partners (code, name, company_id, partner_type) VALUES (?,?,?,'both')",
                         (f"{key.upper()}P", f"{key}거래처", cid)).lastrowid
        po = db.execute("""INSERT INTO purchase_orders (po_number, partner_id, po_date, notes, created_by, company_id)
                           VALUES (?,?,'2026-09-01',?,?,?)""", (f"PO-{tag}", sup, tag, uid, cid)).lastrowid
        db.execute("INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,1,1000,1000)",
                   (po, item))
        qt = db.execute("""INSERT INTO quotations (quote_number, partner_id, quote_date, notes, created_by, company_id)
                           VALUES (?,?,'2026-09-01',?,?,?)""", (f"QT-{tag}", sup, tag, uid, cid)).lastrowid
        so = db.execute("""INSERT INTO sales_orders (so_number, partner_id, order_date, notes, created_by, company_id)
                           VALUES (?,?,'2026-09-01',?,?,?)""", (f"SO-{tag}", sup, tag, uid, cid)).lastrowid
        gr = db.execute("""INSERT INTO goods_receipts (gr_number, po_id, warehouse_id, receipt_date, notes, created_by, company_id)
                           VALUES (?,?,?,'2026-09-02',?,?,?)""", (f"GR-{tag}", po, wh, tag, uid, cid)).lastrowid
        sh = db.execute("""INSERT INTO shipments (ship_number, so_id, warehouse_id, ship_date, notes, created_by, company_id)
                           VALUES (?,?,?,'2026-09-02',?,?,?)""", (f"SH-{tag}", so, wh, tag, uid, cid)).lastrowid
        bom = db.execute("""INSERT INTO bom_headers (product_id, bom_version, created_by, company_id)
                            VALUES (?,?,?,?)""", (item, tag, uid, cid)).lastrowid
        db.execute("INSERT INTO bom_lines (bom_id, component_id, quantity) VALUES (?,?,1)", (bom, item))
        wo = db.execute("""INSERT INTO work_orders (wo_number, product_id, bom_id, planned_qty, notes, created_by, company_id)
                           VALUES (?,?,?,10,?,?,?)""", (f"WO-{tag}", item, bom, tag, uid, cid)).lastrowid
        ids[key] = {"sup": sup, "po": po, "qt": qt, "so": so, "gr": gr, "sh": sh, "bom": bom, "wo": wo}
    db.commit()
    return ids


LISTS = ["/purchase-orders", "/quotations", "/sales-orders", "/bom", "/work-orders",
         "/erp_purch", "/erp_scrm", "/erp_product", "/erp_inventory"]


@pytest.mark.parametrize("user", ["a_mgr", "a_wk"])
@pytest.mark.parametrize("path", LISTS)
def test_list_hides_other_company(docs, login, user, path):
    r = login(user).get(path)
    assert r.status_code == 200
    assert MARK not in r.text


def test_list_shows_own(docs, login):
    c = login("a_mgr")
    assert "PO-A-OWN" in c.get("/purchase-orders").text
    assert "QT-A-OWN" in c.get("/quotations").text
    assert "SO-A-OWN" in c.get("/sales-orders").text
    assert "WO-A-OWN" in c.get("/work-orders").text


def test_staff_sees_all(docs, login):
    assert "PO-B-SECRET" in login("t_staff").get("/purchase-orders").text


DETAILS = ["/purchase-orders/{po}", "/purchase-orders/{po}/edit", "/purchase-orders/{po}/statement",
           "/goods-receipts/new?po_id={po}", "/goods-receipts/{gr}",
           "/quotations/{qt}", "/quotations/{qt}/edit",
           "/sales-orders/{so}", "/sales-orders/{so}/statement", "/shipments/new?so_id={so}", "/shipments/{sh}",
           "/bom/{bom}", "/bom/{bom}/edit", "/work-orders/{wo}", "/work-orders/{wo}/edit",
           "/production-results/new?wo_id={wo}"]


@pytest.mark.parametrize("path", DETAILS)
def test_detail_blocks_other_company(docs, login, path):
    r = login("a_mgr").get(path.format(**docs["b"]))
    assert MARK not in r.text


def test_bom_lines_api_blocks_other_company(docs, login):
    r = login("a_mgr").get(f"/api/bom/{docs['b']['bom']}/lines")
    assert r.status_code != 200 or r.json() == []


ACTIONS = [("/purchase-orders/{po}/confirm", "purchase_orders", "po"),
           ("/purchase-orders/{po}/approve", "purchase_orders", "po"),
           ("/purchase-orders/{po}/reject", "purchase_orders", "po"),
           ("/purchase-orders/{po}/cancel", "purchase_orders", "po"),
           ("/quotations/{qt}/send", "quotations", "qt"),
           ("/quotations/{qt}/accept", "quotations", "qt"),
           ("/quotations/{qt}/reject", "quotations", "qt"),
           ("/sales-orders/{so}/cancel", "sales_orders", "so"),
           ("/work-orders/{wo}/release", "work_orders", "wo"),
           ("/work-orders/{wo}/cancel", "work_orders", "wo")]


@pytest.mark.parametrize("path,table,key", ACTIONS)
def test_action_blocks_other_company(db, docs, login, path, table, key):
    before = db.execute(f"SELECT status FROM {table} WHERE id=?", (docs["b"][key],)).fetchone()[0]
    login("a_mgr").post(path.format(**docs["b"]))
    after = db.execute(f"SELECT status FROM {table} WHERE id=?", (docs["b"][key],)).fetchone()[0]
    assert after == before


def test_bom_delete_blocks_other_company(db, docs, login):
    login("a_mgr").post(f"/bom/{docs['b']['bom']}/delete")
    assert db.execute("SELECT 1 FROM bom_headers WHERE id=?", (docs["b"]["bom"],)).fetchone()


def _lines(item):
    return {"line_nums": "1", "item_id_1": str(item), "qty_1": "5", "price_1": "700"}


def test_po_save_cannot_overwrite_other_company(db, docs, login):
    b = docs["b"]
    login("a_mgr").post("/purchase-orders/save", data={
        "po_id": str(b["po"]), "partner_id": str(docs["a"]["sup"]), "po_date": "2026-09-05",
        "notes": "hijack", **_lines(docs["item"])})
    row = db.execute("SELECT notes, partner_id FROM purchase_orders WHERE id=?", (b["po"],)).fetchone()
    assert row["notes"] == MARK and row["partner_id"] == b["sup"]
    assert db.execute("SELECT COUNT(*) FROM po_lines WHERE po_id=?", (b["po"],)).fetchone()[0] == 1


def test_quote_save_cannot_overwrite_other_company(db, docs, login):
    b = docs["b"]
    login("a_mgr").post("/quotations/save", data={
        "qt_id": str(b["qt"]), "partner_id": str(docs["a"]["sup"]), "quote_date": "2026-09-05",
        "notes": "hijack", **_lines(docs["item"])})
    assert db.execute("SELECT notes FROM quotations WHERE id=?", (b["qt"],)).fetchone()[0] == MARK


def test_bom_save_cannot_overwrite_other_company(db, docs, login):
    b = docs["b"]
    login("a_mgr").post("/bom/save", data={
        "bom_id": str(b["bom"]), "product_id": str(docs["item"]), "bom_version": "hijack",
        "line_nums": "1", "component_id_1": str(docs["item"]), "qty_1": "2"})
    assert db.execute("SELECT bom_version FROM bom_headers WHERE id=?", (b["bom"],)).fetchone()[0] == MARK


def test_wo_save_cannot_overwrite_other_company(db, docs, login):
    b = docs["b"]
    login("a_mgr").post("/work-orders/save", data={
        "wo_id": str(b["wo"]), "bom_id": str(docs["a"]["bom"]), "planned_qty": "99", "notes": "hijack"})
    assert db.execute("SELECT notes FROM work_orders WHERE id=?", (b["wo"],)).fetchone()[0] == MARK


def test_wo_save_rejects_other_company_bom(db, docs, login):
    login("a_mgr").post("/work-orders/save", data={"bom_id": str(docs["b"]["bom"]), "planned_qty": "3"})
    assert not db.execute("SELECT 1 FROM work_orders WHERE bom_id=? AND company_id!=?",
                          (docs["b"]["bom"], db.execute("SELECT company_id FROM bom_headers WHERE id=?",
                                                        (docs["b"]["bom"],)).fetchone()[0])).fetchone()


def test_gr_save_rejects_other_company_po(db, docs, login):
    b = docs["b"]
    login("a_mgr").post("/goods-receipts/save", data={"po_id": str(b["po"]), "receipt_date": "2026-09-06"})
    assert db.execute("SELECT COUNT(*) FROM goods_receipts WHERE po_id=?", (b["po"],)).fetchone()[0] == 1


def test_ship_save_rejects_other_company_so(db, docs, login):
    b = docs["b"]
    login("a_mgr").post("/shipments/save", data={"so_id": str(b["so"]), "ship_date": "2026-09-06"})
    assert db.execute("SELECT COUNT(*) FROM shipments WHERE so_id=?", (b["so"],)).fetchone()[0] == 1


def test_new_rows_stamped_with_company(db, docs, seed, login):
    a = seed["a"]["company"]
    c = login("a_mgr")
    c.post("/purchase-orders/save", data={"partner_id": str(docs["a"]["sup"]), "po_date": "2026-09-07",
                                          "notes": "new-po", **_lines(docs["item"])})
    c.post("/quotations/save", data={"partner_id": str(docs["a"]["sup"]), "quote_date": "2026-09-07",
                                     "notes": "new-qt", **_lines(docs["item"])})
    assert db.execute("SELECT company_id FROM purchase_orders WHERE notes='new-po'").fetchone()[0] == a
    assert db.execute("SELECT company_id FROM quotations WHERE notes='new-qt'").fetchone()[0] == a
    c.post(f"/quotations/{docs['a']['qt']}/accept")
    so = db.execute("SELECT company_id FROM sales_orders WHERE quote_id=?", (docs["a"]["qt"],)).fetchone()
    if so:
        assert so[0] == a


def test_global_search_hides_other_company(docs, login):
    r = login("a_wk").get("/api/search?q=SECRET")
    assert MARK not in r.text


def test_migration_backfills_company(tmp_path):
    import sqlite3
    path = str(tmp_path / "m.db")
    run_migrations(path, upto=67)
    conn = sqlite3.connect(path)
    cid = conn.execute("INSERT INTO client_companies (name) VALUES ('백필')").lastrowid
    uid = conn.execute("INSERT INTO users (username, password, name, role) VALUES ('m','x','m','client')").lastrowid
    conn.execute("INSERT INTO client_users (user_id, company_id) VALUES (?,?)", (uid, cid))
    pid = conn.execute("INSERT INTO partners (code, name, company_id) VALUES ('P','p',?)", (cid,)).lastrowid
    po = conn.execute("INSERT INTO purchase_orders (po_number, partner_id, po_date) VALUES ('PO1',?,'2026-09-01')",
                      (pid,)).lastrowid
    conn.execute("INSERT INTO purchase_orders (po_number, po_date, created_by) VALUES ('PO2','2026-09-01',?)", (uid,))
    conn.execute("INSERT INTO goods_receipts (gr_number, po_id, receipt_date) VALUES ('GR1',?,'2026-09-02')", (po,))
    item = conn.execute("INSERT INTO items (item_code, item_name) VALUES ('I','i')").lastrowid
    conn.execute("INSERT INTO work_orders (wo_number, product_id, planned_qty, created_by) VALUES ('WO1',?,1,?)",
                 (item, uid))
    conn.execute("INSERT INTO work_orders (wo_number, product_id, planned_qty) VALUES ('WO2',?,1)", (item,))
    conn.execute("INSERT INTO purchase_requisitions (pr_number, requester_id, request_date) VALUES ('PR1',?,'2026-09-01')",
                 (uid,))
    conn.commit()
    conn.close()
    run_migrations(path)
    conn = sqlite3.connect(path)
    got = dict(conn.execute("SELECT po_number, company_id FROM purchase_orders").fetchall())
    assert got == {"PO1": cid, "PO2": cid}
    assert conn.execute("SELECT company_id FROM goods_receipts").fetchone()[0] == cid
    got = dict(conn.execute("SELECT wo_number, company_id FROM work_orders").fetchall())
    assert got == {"WO1": cid, "WO2": None}
    assert conn.execute("SELECT company_id FROM purchase_requisitions").fetchone()[0] == cid


@pytest.mark.parametrize("path", ["/work-orders/new", "/work-orders/{wo}/edit", "/production-results/new"])
def test_form_options_hide_other_company(docs, login, path):
    html = login("a_mgr").get(path.format(**docs["a"])).text
    assert MARK not in html
    assert "나테스트근로자" not in html


@pytest.fixture
def pr_b(db, seed):
    pr = db.execute("""INSERT INTO purchase_requisitions (pr_number, requester_id, request_date, status, notes, company_id)
                       VALUES ('PR-B-SECRET',?,'2026-09-01','submitted',?,?)""",
                    (seed["b"]["wk"], MARK, seed["b"]["company"])).lastrowid
    db.commit()
    return pr


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_pr_action_blocks_other_company(db, pr_b, login, action):
    c = login("a_mgr")
    assert MARK not in c.get(f"/purchase-requisitions/{pr_b}").text
    c.post(f"/purchase-requisitions/{pr_b}/{action}")
    assert db.execute("SELECT status FROM purchase_requisitions WHERE id=?", (pr_b,)).fetchone()[0] == "submitted"


@pytest.fixture
def hr_docs(db, seed):
    ids = {}
    for key in ("a", "b"):
        uid = seed[key]["mgr"]
        tag = MARK if key == "b" else "A-OWN"
        hr_doc = db.execute(
            "INSERT INTO erp_docs (user_id, doc_type, title, status) VALUES (?,'hr_task',?,'wait')",
            (uid, f"{tag} 휴가")
        ).lastrowid
        db.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,1,?,'승인','pending')",
            (hr_doc, uid)
        )
        draft = db.execute(
            "INSERT INTO erp_docs (user_id, doc_type, title, status) VALUES (?,'draft',?,'wait')",
            (uid, f"{tag} 기안")
        ).lastrowid
        ids[key] = {"hr": hr_doc, "draft": draft}
    db.commit()
    return ids


DASH_PAGES = ["/erp_hr", "/erp_groupware", "/leave_approvals", "/approvals"]


@pytest.mark.parametrize("path", DASH_PAGES)
def test_dashboard_hides_other_company_docs(hr_docs, login, path):
    r = login("a_mgr").get(path)
    assert r.status_code == 200
    assert MARK not in r.text


def test_dashboard_shows_own_company_docs(hr_docs, login):
    assert "A-OWN" in login("a_mgr").get("/erp_hr").text
    assert "A-OWN" in login("a_mgr").get("/erp_groupware").text
    assert "A-OWN" in login("a_mgr").get("/leave_approvals").text
    assert "A-OWN" in login("a_mgr").get("/approvals").text


def test_worker_hides_coworker_docs(hr_docs, login):
    r = login("a_wk").get("/erp_groupware")
    assert "A-OWN" not in r.text


def test_doc_form_hides_other_company_users(seed, login):
    html = login("a_mgr").get("/draft_doc").text
    assert "나테스트근로자" not in html
