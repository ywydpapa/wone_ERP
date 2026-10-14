import hashlib

import pytest

from routers.erp_master import norm_biz_no, regrade


def _partner(db, cid, code, name, **kw):
    cols = ["code", "name", "company_id", *kw]
    return db.execute(f"INSERT INTO partners ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                      (code, name, cid, *kw.values())).lastrowid


@pytest.fixture
def co(db, seed):
    a, b = seed["a"], seed["b"]
    pid = _partner(db, a["company"], "C1", "가고객", partner_type="customer")
    other = _partner(db, b["company"], "X1", "남의고객", partner_type="customer")
    item = db.execute("INSERT INTO items (item_code, item_name, unit_price, company_id) VALUES ('I1','품목',10000,?)",
                      (a["company"],)).lastrowid
    db.commit()
    return {"cid": a["company"], "mgr": a["mgr"], "wk": a["wk"], "b_mgr": b["mgr"], "pid": pid,
            "other": other, "item": item}


def test_norm_biz_no():
    assert norm_biz_no("2208162517") == "220-81-62517"
    assert norm_biz_no("220-81-62518") is None
    assert norm_biz_no("12345") is None
    assert norm_biz_no("") == ""
    assert norm_biz_no("900101-1234567") == "900101-1234567"


def test_partner_save_contacts_rep_bank(db, co, login):
    r = login("a_mgr").post("/partners/save", data={
        "name": "신규", "biz_no": "2208162517", "rep_id": str(co["wk"]),
        "b_rows": "1", "b_bank_1": "국민", "b_account_1": "123-45", "b_holder_1": "신규(주)", "b_default": "1",
        "c_rows": "1,2,3", "c_name_1": "김담당", "c_email_1": "a@x.kr", "c_role_1_tax": "1",
        "c_name_2": "이과장", "c_mobile_2": "010-1", "c_name_3": "",
    }, follow_redirects=False)
    assert r.status_code == 303
    p = db.execute("SELECT * FROM partners WHERE name='신규'").fetchone()
    assert p["biz_no"] == "220-81-62517"
    assert p["rep_id"] == co["wk"]
    bank = db.execute("SELECT bank, account_no, holder FROM partner_banks WHERE partner_id=?", (p["id"],)).fetchone()
    assert tuple(bank) == ("국민", "123-45", "신규(주)")
    rows = db.execute("SELECT name, roles, sort FROM partner_contacts WHERE partner_id=? ORDER BY sort",
                      (p["id"],)).fetchall()
    assert [tuple(x) for x in rows] == [("김담당", "tax", 0), ("이과장", "", 1)]


def test_partner_save_rejects_bad_input(db, co, login):
    c = login("a_mgr")
    r = c.post("/partners/save", data={"name": "잘못", "biz_no": "220-81-62518"})
    assert r.status_code == 400
    r = c.post("/partners/save", data={"name": "주민", "reg_kind": "rrn", "biz_no": "9901019234567"})
    assert r.status_code == 400
    assert db.execute("SELECT COUNT(*) FROM partners WHERE name IN ('잘못','주민')").fetchone()[0] == 0


def test_partner_save_other_company_rep_ignored(db, co, login):
    login("a_mgr").post("/partners/save", data={"name": "담당", "rep_id": str(co["b_mgr"])})
    assert db.execute("SELECT rep_id FROM partners WHERE name='담당'").fetchone()[0] is None


def test_partner_save_other_company_id_404(db, co, login):
    r = login("a_mgr").post("/partners/save", data={"partner_id": str(co["other"]), "code": "X1", "name": "탈취"})
    assert r.status_code == 404
    assert db.execute("SELECT name FROM partners WHERE id=?", (co["other"],)).fetchone()[0] == "남의고객"


def test_biz_no_dup_check(db, co, login):
    db.execute("UPDATE partners SET biz_no='220-81-62517' WHERE id=?", (co["pid"],))
    db.execute("UPDATE partners SET biz_no='220-81-62517' WHERE id=?", (co["other"],))
    db.commit()
    d = login("a_mgr").get("/api/partners/biz-no?biz_no=2208162517").json()
    assert d["ok"] and [x["code"] for x in d["dups"]] == ["C1"]


def test_invoice_contact_email_used(db, co, login):
    db.execute("UPDATE partners SET email='main@x.kr' WHERE id=?", (co["pid"],))
    db.execute(
        "INSERT INTO partner_contacts (company_id, partner_id, name, email, roles, is_active) VALUES (?,?,'세금',?,'tax',1)",
        (co["cid"], co["pid"], "tax@x.kr"))
    db.commit()
    rows = login("a_mgr").get("/api/partners").json()
    assert next(r for r in rows if r["id"] == co["pid"])["email"] == "tax@x.kr"


def test_partner_prices_scoped(db, co, login):
    c = login("a_mgr")
    r = c.post(f"/partners/{co['pid']}/prices", data={"kind": "sale", "item_id": str(co["item"]), "price": "8,500"},
               follow_redirects=False)
    assert r.status_code == 303
    c.post(f"/partners/{co['pid']}/prices", data={"kind": "sale", "item_id": str(co["item"]), "price": "8000"})
    assert c.get(f"/api/partners/{co['pid']}/prices?kind=sale").json() == {str(co["item"]): 8000}
    assert c.get(f"/api/partners/{co['pid']}/prices?kind=buy").json() == {}
    assert login("b_mgr").get(f"/api/partners/{co['pid']}/prices?kind=sale").json() == {}
    r = login("b_mgr").post(f"/partners/{co['other']}/prices", data={"kind": "sale", "item_id": str(co["item"]),
                                                                     "price": "1"})
    assert r.status_code == 400


def test_regrade_by_sales(db, co):
    vip = db.execute("INSERT INTO partner_grades (company_id, name, min_sales) VALUES (?, 'VIP', 1000000)",
                     (co["cid"],)).lastrowid
    gen = db.execute("INSERT INTO partner_grades (company_id, name, min_sales) VALUES (?, '일반', 0)",
                     (co["cid"],)).lastrowid
    fixed = _partner(db, co["cid"], "C2", "고정", grade_id=gen, grade_fixed=1)
    for pid, amt in ((co["pid"], 1500000), (fixed, 5000000)):
        db.execute("""INSERT INTO tax_invoices (company_id, kind, issue_date, partner_id, supply_amt, vat, total)
                      VALUES (?, '매출', date('now'), ?, ?, 0, ?)""", (co["cid"], pid, amt, amt))
    db.commit()
    assert regrade(db, co["cid"]) == 1
    assert db.execute("SELECT grade_id FROM partners WHERE id=?", (co["pid"],)).fetchone()[0] == vip
    assert db.execute("SELECT grade_id FROM partners WHERE id=?", (fixed,)).fetchone()[0] == gen


def test_lead_convert_moves_history(db, co, login):
    c = login("a_mgr")
    c.post("/crm/leads/save", data={"name": "잠재", "contact_name": "박대리", "phone": "010-2", "biz_no": "1248100998"})
    lid = db.execute("SELECT id FROM crm_leads WHERE name='잠재'").fetchone()[0]
    r = c.post("/crm/activities/save", data={"lead_id": str(lid), "kind": "call", "act_date": "2026-10-01",
                                             "subject": "첫 통화"}, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT status FROM crm_leads WHERE id=?", (lid,)).fetchone()[0] == "contact"
    c.post("/crm/opps/save", data={"title": "도입", "lead_id": str(lid), "stage": "found", "amount": "1,000,000"})

    r = c.post(f"/crm/leads/{lid}/convert", follow_redirects=False)
    lead = db.execute("SELECT status, partner_id FROM crm_leads WHERE id=?", (lid,)).fetchone()
    assert lead["status"] == "converted"
    assert r.headers["location"] == f"/partners/{lead['partner_id']}/edit"
    p = db.execute("SELECT * FROM partners WHERE id=?", (lead["partner_id"],)).fetchone()
    assert (p["company_id"], p["partner_type"], p["biz_no"]) == (co["cid"], "customer", "124-81-00998")
    assert db.execute("SELECT name FROM partner_contacts WHERE partner_id=?", (p["id"],)).fetchone()[0] == "박대리"
    assert tuple(db.execute("SELECT partner_id, lead_id FROM crm_activities").fetchone()) == (p["id"], None)
    assert db.execute("SELECT partner_id FROM crm_opps").fetchone()[0] == p["id"]


def test_lead_other_company_hidden(db, co, login):
    login("a_mgr").post("/crm/leads/save", data={"name": "비밀"})
    lid = db.execute("SELECT id FROM crm_leads WHERE name='비밀'").fetchone()[0]
    c = login("b_mgr")
    assert c.get(f"/crm/leads/{lid}").status_code == 404
    assert c.post(f"/crm/leads/{lid}/convert").status_code == 404
    assert "비밀" not in c.get("/crm/leads").text


def test_activity_rejects_other_company_partner(db, co, login):
    r = login("a_mgr").post("/crm/activities/save", data={"partner_id": str(co["other"]), "kind": "call",
                                                          "act_date": "2026-10-01", "subject": "x"})
    assert r.status_code == 400
    assert db.execute("SELECT COUNT(*) FROM crm_activities").fetchone()[0] == 0


def test_activity_next_date_before_act_date(db, co, login):
    r = login("a_mgr").post("/crm/activities/save", data={"partner_id": str(co["pid"]), "kind": "call",
                                                          "act_date": "2026-10-05", "next_date": "2026-10-01",
                                                          "subject": "x"})
    assert r.status_code == 400


def test_opp_quote_link_and_accept_wins(db, co, login):
    c = login("a_mgr")
    c.post("/crm/opps/save", data={"title": "납품", "partner_id": str(co["pid"]), "stage": "found", "amount": "100000"})
    oid = db.execute("SELECT id FROM crm_opps").fetchone()[0]
    c.post("/quotations/save", data={"qt_id": "0", "partner_id": str(co["pid"]), "quote_date": "2026-10-08",
                                     "line_nums": "1", "item_id_1": str(co["item"]), "qty_1": "1",
                                     "price_1": "10000", "opp_id": str(oid)})
    qid = db.execute("SELECT id FROM quotations").fetchone()[0]
    opp = db.execute("SELECT quote_id, stage FROM crm_opps WHERE id=?", (oid,)).fetchone()
    assert (opp["quote_id"], opp["stage"]) == (qid, "proposal")
    c.post(f"/quotations/{qid}/accept")
    opp = db.execute("SELECT stage, closed_at FROM crm_opps WHERE id=?", (oid,)).fetchone()
    assert opp["stage"] == "won" and opp["closed_at"]


def test_opp_lost_requires_reason(db, co, login):
    c = login("a_mgr")
    c.post("/crm/opps/save", data={"title": "실패건", "partner_id": str(co["pid"]), "stage": "nego"})
    oid = db.execute("SELECT id FROM crm_opps").fetchone()[0]
    assert c.post(f"/crm/opps/{oid}/stage", data={"stage": "lost"}).status_code == 400
    c.post(f"/crm/opps/{oid}/stage", data={"stage": "lost", "lost_reason": "가격"})
    opp = db.execute("SELECT stage, lost_reason FROM crm_opps WHERE id=?", (oid,)).fetchone()
    assert (opp["stage"], opp["lost_reason"]) == ("lost", "가격")
    r = c.post("/crm/opps/save", data={"opp_id": str(oid), "title": "수정", "partner_id": str(co["pid"]),
                                       "stage": "found"})
    assert r.status_code == 400


def test_crm_pages_render(db, co, login):
    c = login("a_mgr")
    for url in ("/erp_scrm", "/crm/activities", "/crm/activities?view=due", "/crm/activities/new",
                "/crm/leads", "/crm/leads/new", "/crm/opps", "/crm/opps?view=list", "/crm/opps/new",
                f"/partners/{co['pid']}", f"/partners/{co['pid']}/edit", f"/partners/{co['pid']}/prices",
                "/partners/settings", "/partners"):
        assert c.get(url).status_code == 200, url


def _opp(db, c, co, stage="found"):
    c.post("/crm/opps/save", data={"title": "기회", "partner_id": str(co["pid"]), "stage": "found", "amount": "100"})
    oid = db.execute("SELECT id FROM crm_opps ORDER BY id DESC").fetchone()[0]
    if stage != "found":
        c.post(f"/crm/opps/{oid}/stage", data={"stage": stage, "lost_reason": "가격"})
    return oid


def test_worker_cannot_convert_or_delete(db, co, login):
    login("a_mgr").post("/crm/leads/save", data={"name": "잠재"})
    lid = db.execute("SELECT id FROM crm_leads WHERE name='잠재'").fetchone()[0]
    c = login("a_wk")
    assert c.post(f"/crm/leads/{lid}/convert").status_code == 403
    assert c.post(f"/crm/leads/{lid}/delete").status_code == 403
    oid = _opp(db, c, co)
    assert c.post(f"/crm/opps/{oid}/delete").status_code == 403
    assert db.execute("SELECT COUNT(*) FROM crm_opps").fetchone()[0] == 1


def test_lead_convert_contact_is_primary(db, co, login):
    c = login("a_mgr")
    c.post("/crm/leads/save", data={"name": "전환", "contact_name": "최대리"})
    lid = db.execute("SELECT id FROM crm_leads WHERE name='전환'").fetchone()[0]
    c.post(f"/crm/leads/{lid}/convert")
    row = db.execute("SELECT is_primary, is_active FROM partner_contacts WHERE name='최대리'").fetchone()
    assert tuple(row) == (1, 1)


def test_closed_opp_needs_reopen_before_reclose(db, co, login):
    c = login("a_mgr")
    oid = _opp(db, c, co, "won")
    assert c.post(f"/crm/opps/{oid}/stage", data={"stage": "lost", "lost_reason": "가격"}).status_code == 400
    assert db.execute("SELECT stage FROM crm_opps WHERE id=?", (oid,)).fetchone()[0] == "won"
    assert login("a_wk").post(f"/crm/opps/{oid}/stage", data={"stage": "nego"}).status_code == 403
    c.post(f"/crm/opps/{oid}/stage", data={"stage": "nego"})
    row = db.execute("SELECT stage, closed_at, lost_reason FROM crm_opps WHERE id=?", (oid,)).fetchone()
    assert tuple(row) == ("nego", "", "")


def test_opp_with_accepted_quote_cannot_reopen(db, co, login):
    c = login("a_mgr")
    oid = _opp(db, c, co, "won")
    qid = db.execute(
        """INSERT INTO quotations (quote_number, partner_id, quote_date, total_amount, tax_amount, status, company_id)
           VALUES ('QT-9',?,'2026-10-01',100,10,'accepted',?)""", (co["pid"], co["cid"])).lastrowid
    db.execute("UPDATE crm_opps SET quote_id=? WHERE id=?", (qid, oid))
    db.commit()
    assert c.post(f"/crm/opps/{oid}/stage", data={"stage": "nego"}).status_code == 400
    assert db.execute("SELECT stage FROM crm_opps WHERE id=?", (oid,)).fetchone()[0] == "won"


def test_no_company_shows_message(db, co, login):
    db.execute("INSERT INTO users (username, password, name, role) VALUES ('nobook', ?, '무소속', 'worker')",
               (hashlib.sha256(b"1234").hexdigest(),))
    db.commit()
    r = login("nobook").get("/crm/leads", follow_redirects=False)
    assert r.status_code == 403
    assert "등록된 회사가 없습니다" in r.text
