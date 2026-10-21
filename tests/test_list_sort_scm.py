def _partner(db, cid, code, kind):
    return db.execute(
        "INSERT INTO partners (code, name, partner_type, company_id) VALUES (?,?,?,?)",
        (code, f"{code}거래처", kind, cid),
    ).lastrowid


def test_po_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    pa = _partner(db, a, "POA", "supplier")
    pb = _partner(db, b, "POB", "supplier")
    db.execute(
        "INSERT INTO purchase_orders (po_number, partner_id, po_date, total_amount, tax_amount, status, company_id) "
        "VALUES ('PO-T1', ?, '2026-09-01', 10000, 1000, 'draft', ?)", (pa, a),
    )
    db.execute(
        "INSERT INTO purchase_orders (po_number, partner_id, po_date, total_amount, tax_amount, status, company_id) "
        "VALUES ('PO-T2', ?, '2026-09-02', 50000, 5000, 'draft', ?)", (pa, a),
    )
    db.execute(
        "INSERT INTO purchase_orders (po_number, partner_id, po_date, total_amount, tax_amount, status, company_id) "
        "VALUES ('PO-B1', ?, '2026-09-01', 99000, 9000, 'draft', ?)", (pb, b),
    )
    db.commit()

    c = login("a_mgr")
    asc = c.get("/purchase-orders?sort=amount&dir=asc").text
    desc = c.get("/purchase-orders?sort=amount&dir=desc").text
    assert asc.index("10,000") < asc.index("50,000")
    assert desc.index("50,000") < desc.index("10,000")
    assert "99,000" not in asc

    assert c.get("/purchase-orders?sort=1;DROP").status_code == 200

    r = c.get("/purchase-orders?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "PO-T1" in r.text and "PO-T2" in r.text
    assert "PO-B1" not in r.text


def test_so_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    pa = _partner(db, a, "SOA", "customer")
    pb = _partner(db, b, "SOB", "customer")
    db.execute(
        "INSERT INTO sales_orders (so_number, partner_id, order_date, total_amount, tax_amount, status, company_id) "
        "VALUES ('SO-T1', ?, '2026-09-01', 15000, 1500, 'confirmed', ?)", (pa, a),
    )
    db.execute(
        "INSERT INTO sales_orders (so_number, partner_id, order_date, total_amount, tax_amount, status, company_id) "
        "VALUES ('SO-T2', ?, '2026-09-02', 65000, 6500, 'confirmed', ?)", (pa, a),
    )
    db.execute(
        "INSERT INTO sales_orders (so_number, partner_id, order_date, total_amount, tax_amount, status, company_id) "
        "VALUES ('SO-B1', ?, '2026-09-01', 95000, 9500, 'confirmed', ?)", (pb, b),
    )
    db.commit()

    c = login("a_mgr")
    asc = c.get("/sales-orders?sort=amount&dir=asc").text
    desc = c.get("/sales-orders?sort=amount&dir=desc").text
    assert asc.index("15,000") < asc.index("65,000")
    assert desc.index("65,000") < desc.index("15,000")

    assert c.get("/sales-orders?sort=1;DROP").status_code == 200

    r = c.get("/sales-orders?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "SO-T1" in r.text and "SO-T2" in r.text
    assert "SO-B1" not in r.text


def test_quote_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    pa = _partner(db, a, "QTA", "customer")
    pb = _partner(db, b, "QTB", "customer")
    db.execute(
        "INSERT INTO quotations (quote_number, partner_id, quote_date, total_amount, tax_amount, status, company_id) "
        "VALUES ('QT-T1', ?, '2026-09-01', 20000, 2000, 'draft', ?)", (pa, a),
    )
    db.execute(
        "INSERT INTO quotations (quote_number, partner_id, quote_date, total_amount, tax_amount, status, company_id) "
        "VALUES ('QT-T2', ?, '2026-09-02', 70000, 7000, 'draft', ?)", (pa, a),
    )
    db.execute(
        "INSERT INTO quotations (quote_number, partner_id, quote_date, total_amount, tax_amount, status, company_id) "
        "VALUES ('QT-B1', ?, '2026-09-01', 88000, 8000, 'draft', ?)", (pb, b),
    )
    db.commit()

    c = login("a_mgr")
    asc = c.get("/quotations?sort=amount&dir=asc").text
    desc = c.get("/quotations?sort=amount&dir=desc").text
    assert asc.index("20,000") < asc.index("70,000")
    assert desc.index("70,000") < desc.index("20,000")

    assert c.get("/quotations?sort=1;DROP").status_code == 200

    r = c.get("/quotations?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "QT-T1" in r.text and "QT-T2" in r.text
    assert "QT-B1" not in r.text


def test_pr_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    mgr, mgr_b = seed["a"]["mgr"], seed["b"]["mgr"]
    pr1 = db.execute(
        "INSERT INTO purchase_requisitions (pr_number, requester_id, request_date, status, company_id) "
        "VALUES ('PR-T1', ?, '2026-09-01', 'draft', ?)", (mgr, a),
    ).lastrowid
    db.execute("INSERT INTO pr_lines (pr_id, line_no, item_name, quantity, estimated_price) VALUES (?,1,'볼트',10,2000)", (pr1,))
    pr2 = db.execute(
        "INSERT INTO purchase_requisitions (pr_number, requester_id, request_date, status, company_id) "
        "VALUES ('PR-T2', ?, '2026-09-02', 'draft', ?)", (mgr, a),
    ).lastrowid
    db.execute("INSERT INTO pr_lines (pr_id, line_no, item_name, quantity, estimated_price) VALUES (?,1,'너트',10,8000)", (pr2,))
    prb = db.execute(
        "INSERT INTO purchase_requisitions (pr_number, requester_id, request_date, status, company_id) "
        "VALUES ('PR-B1', ?, '2026-09-01', 'draft', ?)", (mgr_b, b),
    ).lastrowid
    db.execute("INSERT INTO pr_lines (pr_id, line_no, item_name, quantity, estimated_price) VALUES (?,1,'기타',10,9000)", (prb,))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/purchase-requisitions?sort=amount&dir=asc").text
    desc = c.get("/purchase-requisitions?sort=amount&dir=desc").text
    assert asc.index("20,000") < asc.index("80,000")
    assert desc.index("80,000") < desc.index("20,000")

    assert c.get("/purchase-requisitions?sort=1;DROP").status_code == 200

    r = c.get("/purchase-requisitions?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "PR-T1" in r.text and "PR-T2" in r.text
    assert "PR-B1" not in r.text


def test_rfq_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    db.execute("INSERT INTO rfqs (company_id, rfq_number, rfq_date, status) VALUES (?,'RFQ-T1','2026-09-01','open')", (a,))
    db.execute("INSERT INTO rfqs (company_id, rfq_number, rfq_date, status) VALUES (?,'RFQ-T2','2026-09-10','open')", (a,))
    db.execute("INSERT INTO rfqs (company_id, rfq_number, rfq_date, status) VALUES (?,'RFQ-B1','2026-09-01','open')", (b,))
    db.commit()

    c = login("a_mgr")
    asc = c.get("/rfqs?sort=date&dir=asc").text
    desc = c.get("/rfqs?sort=date&dir=desc").text
    assert asc.index("RFQ-T1") < asc.index("RFQ-T2")
    assert desc.index("RFQ-T2") < desc.index("RFQ-T1")

    assert c.get("/rfqs?sort=1;DROP").status_code == 200

    r = c.get("/rfqs?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "RFQ-T1" in r.text and "RFQ-T2" in r.text
    assert "RFQ-B1" not in r.text


def test_stock_adjust_list_sort_and_csv(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    w1 = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('WA1','본창고',?)", (a,)).lastrowid
    wb = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('WB1','본창고',?)", (b,)).lastrowid
    db.execute(
        "INSERT INTO stock_moves (company_id, kind, move_number, move_date, warehouse_id, reason) "
        "VALUES (?, 'adjust', 'ADJ-T1', '2026-09-01', ?, '실사조정')", (a, w1),
    )
    db.execute(
        "INSERT INTO stock_moves (company_id, kind, move_number, move_date, warehouse_id, reason) "
        "VALUES (?, 'adjust', 'ADJ-T2', '2026-09-10', ?, '실사조정')", (a, w1),
    )
    db.execute(
        "INSERT INTO stock_moves (company_id, kind, move_number, move_date, warehouse_id, reason) "
        "VALUES (?, 'adjust', 'ADJ-B1', '2026-09-01', ?, '실사조정')", (b, wb),
    )
    db.commit()

    c = login("a_mgr")
    asc = c.get("/stock/adjustments?sort=date&dir=asc").text
    desc = c.get("/stock/adjustments?sort=date&dir=desc").text
    assert asc.index("ADJ-T1") < asc.index("ADJ-T2")
    assert desc.index("ADJ-T2") < desc.index("ADJ-T1")

    assert c.get("/stock/adjustments?sort=1;DROP").status_code == 200

    r = c.get("/stock/adjustments?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "ADJ-T1" in r.text and "ADJ-T2" in r.text
    assert "ADJ-B1" not in r.text


def test_stock_transfer_list_export(db, seed, login):
    a = seed["a"]["company"]
    w1 = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('WA2','1창고',?)", (a,)).lastrowid
    w2 = db.execute("INSERT INTO warehouses (code, name, company_id) VALUES ('WA3','2창고',?)", (a,)).lastrowid
    db.execute(
        "INSERT INTO stock_moves (company_id, kind, move_number, move_date, warehouse_id, to_wh_id) "
        "VALUES (?, 'transfer', 'TR-T1', '2026-09-01', ?, ?)", (a, w1, w2),
    )
    db.commit()

    c = login("a_mgr")
    r = c.get("/stock/transfers?export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "TR-T1" in r.text
    assert c.get("/stock/transfers?sort=1;DROP").status_code == 200
