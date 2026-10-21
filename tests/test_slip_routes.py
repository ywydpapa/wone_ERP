from core import books
from routers.erp_sales import _create_ship_slip
from tests.conftest import csrf


def _form(tok, lines, mgr, **kw):
    data = {"csrf_token": tok, "title": "테스트", "slip_type": "대체", "slip_date": "2026-09-15",
            "reviewer_id": str(mgr), "approver_id": str(mgr), "save_mode": "submit",
            "line_count": ",".join(str(i) for i in range(1, len(lines) + 1))}
    for i, (code, dr, cr, pid) in enumerate(lines, 1):
        data[f"account_code_{i}"] = code
        data[f"debit_{i}"] = str(dr)
        data[f"credit_{i}"] = str(cr)
        data[f"partner_id_{i}"] = str(pid or "")
    data.update(kw)
    return data


def test_create_scoped_and_numbered(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/slip", data=_form(csrf(c), [("813", 500, 0, None), ("103", 0, 500, None)], seed["a"]["mgr"]), follow_redirects=False)
    assert r.status_code == 303
    d = db.execute("SELECT * FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()
    assert d["company_id"] == seed["a"]["company"]
    assert d["slip_no"] == "20260915-00001"


def test_required_partner_rejected(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/slip", data=_form(csrf(c), [("110", 500, 0, None), ("401", 0, 500, None)], seed["a"]["mgr"]))
    assert r.status_code == 400


def test_other_company_slip_hidden(db, seed, login):
    doc = books.post(db, seed["b"]["company"], seed["b"]["wk"], "2026-09-15",
                     [{"code": "813", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}],
                     "B사", "manual")
    db.commit()
    c = login("a_wk")
    assert c.get(f"/erp_doc/{doc}").status_code == 404
    assert c.get(f"/edit_slip/{doc}").status_code == 404
    assert "B사" not in c.get("/slip_list").text
    tok = csrf(c)
    assert c.post(f"/api/slip/{doc}/reverse", data={"csrf_token": tok, "slip_date": "2026-09-16"}).status_code == 404


def test_reverse_route(db, seed, login):
    doc = books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-15",
                     [{"code": "813", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}],
                     "A사", "manual")
    db.commit()
    w = login("a_wk")
    assert w.post(f"/api/slip/{doc}/reverse", data={"csrf_token": csrf(w), "slip_date": "2026-09-16"}).status_code == 403
    c = login("a_mgr")
    r = c.post(f"/api/slip/{doc}/reverse", data={"csrf_token": csrf(c), "slip_date": "2026-09-16"})
    assert r.status_code == 200 and r.json()["ok"]
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE reversal_of=?", (doc,)).fetchone()[0] == 1


def test_reverse_blocked_for_payroll_pay(db, seed, login):
    doc = books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-15",
                     [{"code": "254", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}],
                     "급여 지급", "payroll_pay")
    db.commit()
    c = login("a_mgr")
    r = c.post(f"/api/slip/{doc}/reverse", data={"csrf_token": csrf(c), "slip_date": "2026-09-16"})
    assert r.status_code == 400
    assert "급여 관리" in r.json()["error"]
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE reversal_of=?", (doc,)).fetchone()[0] == 0


def test_reverse_blocked_for_fa_disposal(db, seed, login):
    doc = books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-15",
                     [{"code": "206", "debit": 0, "credit": 500}, {"code": "103", "debit": 500, "credit": 0}],
                     "자산 처분", "fa_disposal", 1)
    db.commit()
    c = login("a_mgr")
    r = c.post(f"/api/slip/{doc}/reverse", data={"csrf_token": csrf(c), "slip_date": "2026-09-16"})
    assert r.status_code == 400
    assert "고정자산" in r.json()["error"]
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE reversal_of=?", (doc,)).fetchone()[0] == 0


def test_bulk_reverse_blocked_for_payroll_and_disposal(db, seed, login):
    a = seed["a"]["company"]
    d1 = books.post(db, a, seed["a"]["wk"], "2026-09-15",
                    [{"code": "254", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}],
                    "급여 지급", "payroll_pay")
    d2 = books.post(db, a, seed["a"]["wk"], "2026-09-15",
                    [{"code": "206", "debit": 0, "credit": 500}, {"code": "103", "debit": 500, "credit": 0}],
                    "자산 처분", "fa_disposal", 1)
    db.commit()
    c = login("a_mgr")
    r = c.post("/api/slip/bulk-reverse",
              data={"csrf_token": csrf(c), "doc_ids": f"{d1},{d2}", "slip_date": "2026-09-16"})
    assert r.json() == {"ok": True, "reversed": 0, "failed": 2}
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE reversal_of IN (?,?)", (d1, d2)).fetchone()[0] == 0


def test_reverse_blocked_when_tax_invoice_linked(db, seed, login):
    a = seed["a"]["company"]
    pid = db.execute("INSERT INTO partners (code, name, company_id) VALUES ('P1','거래처P',?)", (a,)).lastrowid
    doc = _create_ship_slip(db, a, 1, "SH-1", 10000, seed["a"]["wk"], "2026-09-15", pid)
    db.commit()
    c = login("a_mgr")
    r = c.post(f"/api/slip/{doc}/reverse", data={"csrf_token": csrf(c), "slip_date": "2026-09-16"})
    assert r.status_code == 400
    assert "세금계산서" in r.json()["error"]
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE reversal_of=?", (doc,)).fetchone()[0] == 0


def test_done_slip_not_editable(db, seed, login):
    doc = books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-15",
                     [{"code": "813", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}],
                     "A사", "manual")
    db.commit()
    c = login("a_wk")
    r = c.post(f"/api/slip/{doc}", data=_form(csrf(c), [("813", 700, 0, None), ("103", 0, 700, None)], seed["a"]["mgr"]))
    assert r.status_code == 400


def test_detail_hides_edit_delete_when_closed(db, seed, login):
    c = login("a_wk")
    c.post("/api/slip", data=_form(csrf(c), [("813", 500, 0, None), ("103", 0, 500, None)], seed["a"]["mgr"],
                                   save_mode="draft"))
    doc = db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,9,'closed')", (seed["a"]["company"],))
    db.commit()
    html = c.get(f"/erp_doc/{doc}").text
    assert "마감됨" in html
    assert f"/edit_slip/{doc}" not in html
    assert 'data-action="deleteDoc"' not in html


def test_approval_blocked_in_closed_period(db, seed, login):
    c = login("a_wk")
    c.post("/api/slip", data=_form(csrf(c), [("813", 500, 0, None), ("103", 0, 500, None)], seed["a"]["mgr"]))
    doc = db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,2026,9,'closed')", (seed["a"]["company"],))
    db.commit()
    m = login("a_mgr")
    tok = csrf(m, f"/erp_doc/{doc}")
    m.post(f"/api/erp_docs/{doc}/approve", data={"csrf_token": tok})
    r = m.post(f"/api/erp_docs/{doc}/approve", data={"csrf_token": tok})
    assert r.status_code == 400
    assert db.execute("SELECT status FROM erp_docs WHERE id=?", (doc,)).fetchone()["status"] != "done"


def _submit(db, seed, login):
    c = login("a_wk")
    c.post("/api/slip", data=_form(csrf(c), [("813", 500, 0, None), ("103", 0, 500, None)], seed["a"]["mgr"]))
    return db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]


def test_staff_cannot_touch_client_slip(db, seed, login):
    doc = _submit(db, seed, login)
    s = login("t_staff")
    tok = csrf(s, "/")
    assert s.post(f"/api/erp_docs/{doc}/approve", data={"csrf_token": tok}).status_code == 404
    assert s.post(f"/api/erp_docs/{doc}/reject", data={"csrf_token": tok, "comment": "x"}).status_code == 404
    r = s.post(f"/api/erp_docs/{doc}/status", data={"csrf_token": tok, "status": "done"})
    assert r.status_code == 400
    assert db.execute("SELECT status FROM erp_docs WHERE id=?", (doc,)).fetchone()["status"] == "wait"


def test_signers_must_be_same_book(db, seed, login):
    c = login("a_wk")
    lines = [("813", 500, 0, None), ("103", 0, 500, None)]
    before = db.execute("SELECT COUNT(*) FROM erp_docs").fetchone()[0]
    assert c.post("/api/slip", data=_form(csrf(c), lines, seed["a"]["mgr"], approver_id=str(seed["b"]["mgr"]))).status_code == 400
    assert c.post("/api/slip", data=_form(csrf(c), lines, seed["a"]["mgr"], approver_id=str(seed["a"]["wk"]))).status_code == 400
    assert db.execute("SELECT COUNT(*) FROM erp_docs").fetchone()[0] == before


def test_bad_slip_date(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/slip", data=_form(csrf(c), [("813", 500, 0, None), ("103", 0, 500, None)], seed["a"]["mgr"],
                                       slip_date="2026-13-40"))
    assert r.status_code == 400


def test_client_reads_own_company_slip(db, seed, login):
    doc = books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-15",
                     [{"code": "813", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}],
                     "A사", "manual")
    db.commit()
    m = login("a_mgr")
    assert m.get(f"/erp_doc/{doc}").status_code == 200
    assert m.get(f"/erp_doc/{doc}/trade_statement").status_code == 200
