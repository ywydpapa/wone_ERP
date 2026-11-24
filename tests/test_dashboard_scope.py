from core import books


def _seed_b_slips(db, seed):
    b = seed["b"]["company"]
    books.post(db, b, seed["b"]["wk"], "2026-09-10",
               [{"code": "813", "debit": 999999, "credit": 0}, {"code": "103", "debit": 0, "credit": 999999}],
               "B사비밀전표", "manual")
    db.execute(
        "INSERT INTO erp_docs (user_id, doc_type, title, status, company_id, slip_date) VALUES (?,?,?,?,?,?)",
        (seed["b"]["wk"], "expense", "B사대기전표", "wait", b, "2026-09-11"),
    )
    db.commit()


def test_outflow_list_scoped_to_book(db, seed, login):
    _seed_b_slips(db, seed)
    html = login("a_mgr").get("/outflow_list").text
    assert "B사비밀전표" not in html
    assert "B사대기전표" not in html


def test_pending_payments_scoped_to_book(db, seed, login):
    _seed_b_slips(db, seed)
    html = login("a_mgr").get("/pending_payments").text
    assert "B사비밀전표" not in html
    assert "B사대기전표" not in html


def test_approval_pending_scoped_to_book(db, seed, login):
    _seed_b_slips(db, seed)
    html = login("a_mgr").get("/approvals").text
    assert "B사비밀전표" not in html
    assert "B사대기전표" not in html


def test_erp_dash_scoped_for_staff(db, seed, login):
    _seed_b_slips(db, seed)
    html = login("t_staff").get("/erp_dash").text
    assert "B사비밀전표" not in html
    assert "B사대기전표" not in html


def test_removed_dashboard_stubs_404(db, seed, login):
    c = login("a_mgr")
    for path in ("/production_status", "/equipment_alerts", "/po_status", "/delayed_delivery", "/po_pending",
                "/outbound_status", "/low_stock_alerts", "/sales_leads", "/voc_list", "/recruitment_status"):
        assert c.get(path).status_code == 404, path


def _set_role(db, seed, role):
    db.execute("UPDATE client_users SET client_role=? WHERE user_id=?", (role, seed["a"]["mgr"]))
    db.commit()


def test_ops_dash_no_hr(db, seed, login):
    _set_role(db, seed, "ops")
    html = login("a_mgr").get("/").text
    assert "이번 달 급여 미확정" not in html
    assert 'name="m_payroll"' not in html
    assert "근태 소명" in html


def test_hr_dash_no_requests(db, seed, login):
    _set_role(db, seed, "hr")
    html = login("a_mgr").get("/").text
    assert "/client/requests" not in html
    assert "이번 달 급여 미확정" in html


def test_ops_widget_no_hr(db, seed, login):
    _set_role(db, seed, "ops")
    login("a_mgr").post("/dashboard/widgets", data={"m_payroll": "1", "m_requests": "1"})
    row = db.execute("SELECT widgets FROM dashboard_prefs WHERE user_id=?", (seed["a"]["mgr"],)).fetchone()
    assert "m_payroll" not in row["widgets"]
    assert "m_requests" in row["widgets"]
