from tests.conftest import csrf
from routers.erp_accounting import _create_payroll_slip
from routers.erp_sales import _create_ship_slip
from routers.erp_purchase import _create_gr_slip


def _partner(db, book):
    return db.execute("INSERT INTO partners (code, name, company_id) VALUES ('C1','거래처',?)", (book,)).lastrowid


def test_ship_and_gr(db, seed):
    a = seed["a"]["company"]
    pid = _partner(db, a)
    doc = _create_ship_slip(db, a, 1, "SH-1", 11000, seed["a"]["wk"], "2026-09-20", pid)
    d = db.execute("SELECT * FROM erp_docs WHERE id=?", (doc,)).fetchone()
    assert (d["company_id"], d["source_type"], d["source_id"], d["status"]) == (a, "ship", 1, "done")
    assert d["slip_no"].startswith("20260920-")
    doc = _create_gr_slip(db, a, 2, "GR-1", 5000, seed["a"]["wk"], "2026-09-20", pid)
    assert db.execute("SELECT source_type FROM erp_docs WHERE id=?", (doc,)).fetchone()[0] == "gr"


def test_payroll(db, seed):
    a = seed["a"]["company"]
    ps = {"id": 5, "pay_year": 2026, "pay_month": 9, "pay_date": "2026-09-25", "gross_pay": 3000000,
          "net_pay": 2700000, "income_tax": 100000, "resident_tax": 10000, "national_pension": 100000,
          "health_insurance": 60000, "long_care": 8000, "employment_insurance": 22000}
    doc = _create_payroll_slip(db, a, ps, "홍길동", seed["a"]["mgr"])
    d = db.execute("SELECT * FROM erp_docs WHERE id=?", (doc,)).fetchone()
    assert (d["company_id"], d["source_type"], d["source_id"], d["payslip_id"]) == (a, "payroll", 5, 5)
    s = db.execute("SELECT SUM(debit), SUM(credit) FROM slip_lines WHERE doc_id=?", (doc,)).fetchone()
    assert s[0] == s[1]


def test_closed_period_raises(db, seed):
    import pytest
    a = seed["a"]["company"]
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,9,'closed')", (a,))
    with pytest.raises(ValueError):
        _create_ship_slip(db, a, 1, "SH-1", 1000, seed["a"]["wk"], "2026-09-20", _partner(db, a))


def test_ship_save_rolls_back_when_period_closed(db, seed, login):
    a = seed["a"]["company"]
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,9,'closed')", (a,))
    partner_id = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('C1','가고객',?,'customer')", (a,)
    ).lastrowid
    item_id = db.execute(
        "INSERT INTO items (item_code, item_name, unit_price, company_id) VALUES ('I1','품목1',1000,?)", (a,)
    ).lastrowid
    wh_id = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','창고1',?)", (a,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,100)", (item_id, wh_id))
    so_id = db.execute(
        """INSERT INTO sales_orders (so_number, partner_id, order_date, status, total_amount, tax_amount, created_by, company_id)
           VALUES ('SO-2026-0001',?,'2026-09-20','confirmed',10000,1000,?,?)""",
        (partner_id, seed["a"]["wk"], seed["a"]["company"]),
    ).lastrowid
    so_line_id = db.execute(
        "INSERT INTO so_lines (so_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,10,1000,10000)",
        (so_id, item_id),
    ).lastrowid
    db.commit()

    ship_count = db.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
    trans_count = db.execute("SELECT COUNT(*) FROM stock_transactions").fetchone()[0]

    c = login("a_wk")
    tok = csrf(c, f"/shipments/new?so_id={so_id}")
    r = c.post("/shipments/save", data={
        "csrf_token": tok,
        "so_id": str(so_id),
        "warehouse_id": str(wh_id),
        "ship_date": "2026-09-20",
        "line_nums": "1",
        "so_line_id_1": str(so_line_id),
        "item_id_1": str(item_id),
        "ship_qty_1": "10",
    }, follow_redirects=False)
    assert r.status_code == 400
    assert "마감된 회계기간입니다." in r.json()["error"]

    assert db.execute("SELECT COUNT(*) FROM shipments").fetchone()[0] == ship_count
    assert db.execute("SELECT COUNT(*) FROM stock_transactions").fetchone()[0] == trans_count
    assert db.execute("SELECT COUNT(*) FROM tax_invoices").fetchone()[0] == 0


def test_ship_save_normal(db, seed, login):
    a = seed["a"]["company"]
    partner_id = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('C1','가고객',?,'customer')", (a,)
    ).lastrowid
    item_id = db.execute(
        "INSERT INTO items (item_code, item_name, unit_price, company_id) VALUES ('I1','품목1',1000,?)", (a,)
    ).lastrowid
    wh_id = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','창고1',?)", (a,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,100)", (item_id, wh_id))
    so_id = db.execute(
        """INSERT INTO sales_orders (so_number, partner_id, order_date, status, total_amount, tax_amount, created_by, company_id)
           VALUES ('SO-2026-0001',?,'2026-09-20','confirmed',10000,1000,?,?)""",
        (partner_id, seed["a"]["wk"], seed["a"]["company"]),
    ).lastrowid
    so_line_id = db.execute(
        "INSERT INTO so_lines (so_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,10,1000,10000)",
        (so_id, item_id),
    ).lastrowid
    db.commit()

    c = login("a_wk")
    tok = csrf(c, f"/shipments/new?so_id={so_id}")
    r = c.post("/shipments/save", data={
        "csrf_token": tok,
        "so_id": str(so_id),
        "warehouse_id": str(wh_id),
        "ship_date": "2026-09-20",
        "line_nums": "1",
        "so_line_id_1": str(so_line_id),
        "item_id_1": str(item_id),
        "ship_qty_1": "10",
    }, follow_redirects=False)
    assert r.status_code == 303
    inv = db.execute("SELECT * FROM tax_invoices WHERE source_type='ship'").fetchone()
    assert (inv["supply_amt"], inv["vat"], inv["partner_id"]) == (10000, 1000, partner_id)
    item = db.execute("SELECT name, qty, unit_price, supply_amt FROM tax_invoice_items WHERE invoice_id=?", (inv["id"],)).fetchone()
    assert tuple(item) == ("품목1", 10, 1000, 10000)


def test_gr_save_rolls_back_when_period_closed(db, seed, login):
    a = seed["a"]["company"]
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,9,'closed')", (a,))
    partner_id = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES ('S1','가공급',?,'supplier')", (a,)
    ).lastrowid
    item_id = db.execute(
        "INSERT INTO items (item_code, item_name, unit_price, company_id) VALUES ('I1','품목1',1000,?)", (a,)
    ).lastrowid
    wh_id = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','창고1',?)", (a,)).lastrowid
    po_id = db.execute(
        """INSERT INTO purchase_orders (po_number, partner_id, po_date, status, total_amount, tax_amount, created_by, company_id)
           VALUES ('PO-2026-0001',?,'2026-09-20','confirmed',10000,1000,?,?)""",
        (partner_id, seed["a"]["wk"], seed["a"]["company"]),
    ).lastrowid
    po_line_id = db.execute(
        "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,10,1000,10000)",
        (po_id, item_id),
    ).lastrowid
    db.commit()

    gr_count = db.execute("SELECT COUNT(*) FROM goods_receipts").fetchone()[0]
    trans_count = db.execute("SELECT COUNT(*) FROM stock_transactions").fetchone()[0]

    c = login("a_wk")
    tok = csrf(c, f"/goods-receipts/new?po_id={po_id}")
    r = c.post("/goods-receipts/save", data={
        "csrf_token": tok,
        "po_id": str(po_id),
        "warehouse_id": str(wh_id),
        "receipt_date": "2026-09-20",
        "line_nums": "1",
        "po_line_id_1": str(po_line_id),
        "item_id_1": str(item_id),
        "recv_qty_1": "10",
        "defect_qty_1": "0",
    }, follow_redirects=False)
    assert r.status_code == 400
    assert "마감된 회계기간입니다." in r.json()["error"]

    assert db.execute("SELECT COUNT(*) FROM goods_receipts").fetchone()[0] == gr_count
    assert db.execute("SELECT COUNT(*) FROM stock_transactions").fetchone()[0] == trans_count
    assert db.execute("SELECT COUNT(*) FROM tax_invoices").fetchone()[0] == 0


def test_payroll_confirm_rolls_back_when_period_closed(db, seed, login):
    a = seed["a"]["company"]
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,9,'closed')", (a,))
    db.execute(
        "INSERT INTO attendance_closings (year, month, company_id, status) VALUES (2026,9,?,'closed')", (a,)
    )
    emp_id = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()["id"]
    db.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay,
               total_deduction, net_pay, pay_date, status)
           VALUES (?,2026,9,3000000,300000,2700000,'2026-09-25','draft')""",
        (emp_id,),
    )
    db.commit()

    c = login("a_mgr")
    tok = csrf(c, "/payroll")
    r = c.post("/payroll/confirm", data={
        "csrf_token": tok,
        "year": "2026",
        "month": "9",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error=%EB%A7%88%EA%B0%90" in r.headers["location"]

    ps = db.execute("SELECT status FROM payslips WHERE employee_id=? AND pay_year=2026 AND pay_month=9", (emp_id,)).fetchone()
    assert ps["status"] == "draft"
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE payslip_id IS NOT NULL").fetchone()[0] == 0


def test_ship_save_stock_shortage_message(db, seed, login):
    a = seed["a"]["company"]
    item_id = db.execute(
        "INSERT INTO items (item_code, item_name, unit_price, company_id) VALUES ('I1','품목1',1000,?)", (a,)
    ).lastrowid
    wh_id = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('W1','창고1',?)", (a,)).lastrowid
    db.execute("INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,3)", (item_id, wh_id))
    db.commit()
    c = login("a_wk")
    r = c.post("/shipments/save", data={
        "csrf_token": csrf(c, "/shipments/new"), "warehouse_id": str(wh_id), "ship_date": "2026-09-20",
        "line_nums": "1", "item_id_1": str(item_id), "ship_qty_1": "10",
    }, follow_redirects=False)
    assert r.status_code == 400
    assert r.json()["error"] == "재고 부족: 품목1 (재고 3, 출고 10)"
    r = c.post("/shipments/save", data={"csrf_token": csrf(c, "/shipments/new"), "warehouse_id": "0"}, follow_redirects=False)
    assert r.status_code == 400 and "창고" in r.json()["error"]
