import json

from core import audit, books
from tests.conftest import csrf


def L(code, dr=0, cr=0, **kw):
    return {"code": code, "debit": dr, "credit": cr, **kw}


def test_diff():
    assert audit.diff({"a": 1, "b": "x"}, {"a": "1", "b": "y"}) == {"b": ["x", "y"]}


def test_post_logs_audit(db, seed):
    a = seed["a"]["company"]
    uid = seed["a"]["wk"]
    doc = books.post(db, a, uid, "2026-09-10", [L("813", 500), L("103", cr=500)], "통신비", "ship", 7)
    row = db.execute("SELECT * FROM audit_logs WHERE action='post'").fetchone()
    assert row["target_type"] == "slip" and row["target_id"] == doc and row["company_id"] == a
    assert row["user_id"] == uid
    slip_no = db.execute("SELECT slip_no FROM erp_docs WHERE id=?", (doc,)).fetchone()[0]
    assert slip_no in row["summary"]


def test_reverse_logs_audit(db, seed):
    a = seed["a"]["company"]
    uid = seed["a"]["wk"]
    doc = books.post(db, a, uid, "2026-09-10", [L("813", 500), L("103", cr=500)], "통신비", "ship", 7)
    books.reverse(db, doc, uid, "2026-09-11")
    row = db.execute("SELECT * FROM audit_logs WHERE action='reverse'").fetchone()
    assert row["target_id"] == doc


def _partner(db, book, code="P1"):
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES (?,?,?)", (code, "거래처" + code, book)).lastrowid
    db.commit()
    return pid


def test_invoice_create_logs_audit(db, seed, login):
    a = seed["a"]["company"]
    pid = _partner(db, a)
    c = login("a_mgr")
    data = {"csrf_token": csrf(c, "/tax-invoices/new"), "tax_type": "과세", "evidence": "세금계산서",
            "issue_date": "2026-09-20", "line_count": "1", "is_electronic": "1", "deduct": "1",
            "kind": "매출", "partner_id": pid, "item_supply_1": "10,000", "item_vat_1": "1,000",
            "acct": "401", "pay": "110", "receipt_type": "영수"}
    r = c.post("/tax-invoices", data=data, follow_redirects=False)
    assert r.status_code == 303
    rows = db.execute("SELECT * FROM audit_logs WHERE action='invoice_create'").fetchall()
    assert len(rows) == 1
    assert rows[0]["company_id"] == a


def test_gr_confirm_logs_audit(db, seed, login):
    a, uid = seed["a"]["company"], seed["a"]["wk"]
    sup = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('S1','공급1',?,'supplier')", (a,)
    ).lastrowid
    item = db.execute(
        "INSERT INTO items (item_code, item_name, unit_price, company_id) VALUES ('I1','품목1',1000,?)", (a,)
    ).lastrowid
    wh = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','창고1',?)", (a,)).lastrowid
    po = db.execute(
        """INSERT INTO purchase_orders (po_number, partner_id, po_date, status, total_amount, tax_amount, created_by, company_id)
           VALUES ('PO-2026-0001',?,'2026-09-01','confirmed',10000,0,?,?)""",
        (sup, uid, a),
    ).lastrowid
    line = db.execute(
        "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,10,1000,10000)",
        (po, item),
    ).lastrowid
    db.commit()

    c = login("a_wk")
    r = c.post("/goods-receipts/save", data={
        "csrf_token": csrf(c, f"/goods-receipts/new?po_id={po}"), "po_id": str(po), "warehouse_id": str(wh),
        "receipt_date": "2026-09-10", "line_nums": "1", "po_line_id_1": str(line), "item_id_1": str(item),
        "recv_qty_1": "10", "defect_qty_1": "0",
    }, follow_redirects=False)
    assert r.status_code == 303

    rows = db.execute("SELECT * FROM audit_logs WHERE action='gr_confirm'").fetchall()
    assert len(rows) == 1
    assert rows[0]["target_type"] == "gr" and rows[0]["company_id"] == a


def test_partner_update_logs_audit_diff_only_changed(db, seed, login):
    a = seed["a"]["company"]
    c = login("a_mgr")
    c.post("/partners/save", data={"name": "원래거래처"}, follow_redirects=False)
    row = db.execute(
        "SELECT id, code FROM partners WHERE company_id=? AND name='원래거래처'", (a,)
    ).fetchone()

    c.post("/partners/save", data={"partner_id": str(row["id"]), "code": row["code"], "name": "새거래처"},
           follow_redirects=False)

    log_row = db.execute("SELECT * FROM audit_logs WHERE action='partner_update'").fetchone()
    assert json.loads(log_row["detail"]) == {"name": ["원래거래처", "새거래처"]}
    assert log_row["company_id"] == a


def test_employee_update_logs_audit_diff_only_changed(db, seed, login):
    a = seed["a"]["company"]
    emp_id = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()["id"]
    c = login("t_staff")
    r = c.post(f"/hr/employees/{emp_id}/edit", data={
        "name": "가테스트근로자", "dept": "회계팀", "company_id": str(a),
    }, follow_redirects=False)
    assert r.status_code == 303

    log_row = db.execute("SELECT * FROM audit_logs WHERE action='employee_update'").fetchone()
    assert json.loads(log_row["detail"]) == {"dept": ["경영지원팀", "회계팀"]}
    assert log_row["company_id"] == a


def test_fi_close_reopen_logs_audit(db, seed, login):
    m = login("a_mgr")
    tok = csrf(m, "/fi/closing")
    m.post("/fi/closing/close", data={"csrf_token": tok, "year": "2026", "month": "8"}, follow_redirects=False)
    close_row = db.execute("SELECT * FROM audit_logs WHERE action='close'").fetchone()
    assert close_row["target_type"] == "closing"

    closing_id = db.execute("SELECT id FROM fi_closings WHERE year=2026 AND month=8").fetchone()[0]
    m.post("/fi/closing/reopen", data={"csrf_token": tok, "closing_id": closing_id, "reason": "수정",
                                        "password": "1234"}, follow_redirects=False)
    reopen_row = db.execute("SELECT * FROM audit_logs WHERE action='reopen'").fetchone()
    assert reopen_row["target_type"] == "closing"
