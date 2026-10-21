def _wo_with_result(db, company, mgr, item_code, good, defect):
    item = db.execute(
        "INSERT INTO items (item_code, item_name, company_id) VALUES (?,?,?)", (item_code, item_code, company)
    ).lastrowid
    wo = db.execute(
        """INSERT INTO work_orders (wo_number, product_id, planned_qty, planned_start, created_by, company_id, status)
           VALUES (?,?,20,'2026-09-01',?,?,'in_progress')""",
        (f"WO-{item_code}", item, mgr, company),
    ).lastrowid
    db.execute(
        "INSERT INTO production_results (wo_id, result_date, good_qty, defect_qty, created_by) VALUES (?,'2026-09-10',?,?,?)",
        (wo, good, defect, mgr),
    )
    db.commit()
    return wo


def test_wo_report_excludes_other_company(db, seed, login):
    a, b = seed["a"]["company"], seed["b"]["company"]
    _wo_with_result(db, a, seed["a"]["mgr"], "P-A", 18, 2)
    _wo_with_result(db, b, seed["b"]["mgr"], "P-B", 10, 0)

    html = login("a_mgr").get("/work-orders/report?from=2026-09-01&to=2026-09-30").text
    assert "P-A" in html
    assert "P-B" not in html


def test_wo_report_yield_rate(db, seed, login):
    a = seed["a"]["company"]
    _wo_with_result(db, a, seed["a"]["mgr"], "P-C", 18, 2)

    html = login("a_mgr").get("/work-orders/report?from=2026-09-01&to=2026-09-30").text
    assert "90.0%" in html
