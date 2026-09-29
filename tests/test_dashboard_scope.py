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
    html = login("a_mgr").get("/approval_pending").text
    assert "B사비밀전표" not in html
    assert "B사대기전표" not in html


def test_erp_dash_scoped_for_staff(db, seed, login):
    _seed_b_slips(db, seed)
    html = login("t_staff").get("/erp_dash").text
    assert "B사비밀전표" not in html
    assert "B사대기전표" not in html
