import hashlib

import pytest


def _make_po(db, company, uid, no):
    sup = db.execute(
        "INSERT INTO partners (code, name, company_id, partner_type) VALUES (?,?,?,'supplier')",
        (f"S{no}", f"공급{no}", company),
    ).lastrowid
    item = db.execute(
        "INSERT INTO items (item_code, item_name, unit_price, company_id) VALUES (?,'품목',1000,?)",
        (f"I{no}", company),
    ).lastrowid
    po = db.execute(
        """INSERT INTO purchase_orders (po_number, partner_id, po_date, status, total_amount, tax_amount, created_by, company_id)
           VALUES (?,?,'2026-09-01','draft',10000,1000,?,?)""",
        (f"PO-2026-{no}", sup, uid, company),
    ).lastrowid
    db.execute(
        "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,1,?,10,1000,10000)",
        (po, item),
    )
    db.commit()
    return po


@pytest.fixture
def po_a(db, seed):
    return _make_po(db, seed["a"]["company"], seed["a"]["mgr"], "0001")


@pytest.fixture
def a_wk2(db, seed):
    # a사 소속이지만 결재자로 지정되지 않은 다른 근로자
    pw = hashlib.sha256(b"1234").hexdigest()
    uid = db.execute(
        "INSERT INTO users (username, password, name, role) VALUES ('a_wk2',?,?,'worker')",
        (pw, "가테스트근로자2"),
    ).lastrowid
    db.execute(
        "INSERT INTO employees (user_id, name, company_id) VALUES (?,?,?)",
        (uid, "가테스트근로자2", seed["a"]["company"]),
    )
    db.commit()
    return uid


def _confirm(c, po, approver_id):
    return c.post(f"/purchase-orders/{po}/confirm", data={"approver_id": str(approver_id)}, follow_redirects=False)


def _line(db, po):
    return db.execute(
        """SELECT al.approver_id, al.status, al.comment, d.status AS doc_status FROM purchase_orders po
           JOIN erp_docs d ON d.id = po.doc_id JOIN approval_lines al ON al.doc_id = d.id AND al.step = 1
           WHERE po.id=?""", (po,)
    ).fetchone()


def test_submit_binds_designated_approver(db, seed, po_a, login):
    c = login("a_mgr")
    r = _confirm(c, po_a, seed["a"]["wk"])
    assert r.status_code == 303
    row = db.execute(
        "SELECT status FROM purchase_orders WHERE id=?", (po_a,)
    ).fetchone()
    assert row["status"] == "pending_approval"
    appr = _line(db, po_a)
    assert appr["approver_id"] == seed["a"]["wk"]
    assert appr["status"] == "pending" and appr["doc_status"] == "wait"
    assert db.execute(
        "SELECT 1 FROM notifications WHERE user_id=? AND title='결재 요청'", (seed["a"]["wk"],)
    ).fetchone()


def test_submit_without_approver_400(po_a, login):
    c = login("a_mgr")
    r = _confirm(c, po_a, 0)
    assert r.status_code == 400


def test_submit_other_company_approver_400(seed, po_a, login):
    c = login("a_mgr")
    r = _confirm(c, po_a, seed["b"]["wk"])
    assert r.status_code == 400


def test_other_company_user_cannot_approve(db, seed, po_a, login):
    login("a_mgr").post(f"/purchase-orders/{po_a}/confirm", data={"approver_id": str(seed["a"]["wk"])})
    r = login("b_wk").post(f"/purchase-orders/{po_a}/approve", follow_redirects=False)
    assert r.status_code == 404
    doc_id = db.execute("SELECT doc_id FROM purchase_orders WHERE id=?", (po_a,)).fetchone()[0]
    assert login("b_mgr").post(f"/api/erp_docs/{doc_id}/approve").status_code == 404
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "pending_approval"


def test_non_designated_coworker_cannot_approve(db, seed, po_a, a_wk2, login):
    login("a_mgr").post(f"/purchase-orders/{po_a}/confirm", data={"approver_id": str(seed["a"]["wk"])})
    r = login("a_wk2").post(f"/purchase-orders/{po_a}/approve", follow_redirects=False)
    assert r.status_code == 403
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "pending_approval"


def test_designated_approver_can_approve(db, seed, po_a, login):
    login("a_mgr").post(f"/purchase-orders/{po_a}/confirm", data={"approver_id": str(seed["a"]["wk"])})
    r = login("a_wk").post(f"/purchase-orders/{po_a}/approve", follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "confirmed"
    appr = _line(db, po_a)
    assert appr["status"] == "approved" and appr["doc_status"] == "done"
    log = db.execute(
        "SELECT 1 FROM audit_logs WHERE action='po_approve' AND target_type='po' AND target_id=?", (po_a,)
    ).fetchone()
    assert log is not None


def test_client_cannot_approve_on_behalf(db, seed, po_a, login):
    # 결재선에 없는 담당자 대행 승인 불가
    login("a_mgr").post(f"/purchase-orders/{po_a}/confirm", data={"approver_id": str(seed["a"]["wk"])})
    r = login("a_mgr").post(f"/purchase-orders/{po_a}/approve", follow_redirects=False)
    assert r.status_code == 403
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "pending_approval"


def test_approve_from_approval_box(db, seed, po_a, login):
    login("a_mgr").post(f"/purchase-orders/{po_a}/confirm", data={"approver_id": str(seed["a"]["wk"])})
    doc_id = db.execute("SELECT doc_id FROM purchase_orders WHERE id=?", (po_a,)).fetchone()[0]
    wk = login("a_wk")
    assert "PO-2026-0001" in wk.get("/approvals?box=wait").text
    assert wk.post(f"/api/erp_docs/{doc_id}/approve").json()["new_status"] == "done"
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "confirmed"
    assert "결재선" in login("a_mgr").get(f"/purchase-orders/{po_a}").text


def test_preset_line_used(db, seed, po_a, a_wk2, login):
    mgr = login("a_mgr")
    mgr.post("/approval-lines/po", data={"line_role": ["결재", "결재"], "line_user": [str(a_wk2), str(seed["a"]["wk"])]})
    assert _confirm(mgr, po_a, 0).status_code == 303
    assert login("a_wk").post(f"/purchase-orders/{po_a}/approve", follow_redirects=False).status_code == 403
    login("a_wk2").post(f"/purchase-orders/{po_a}/approve")
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "pending_approval"
    login("a_wk").post(f"/purchase-orders/{po_a}/approve")
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "confirmed"


def test_designated_approver_can_reject(db, seed, po_a, login):
    login("a_mgr").post(f"/purchase-orders/{po_a}/confirm", data={"approver_id": str(seed["a"]["wk"])})
    r = login("a_wk").post(f"/purchase-orders/{po_a}/reject", data={"comment": "금액 확인 필요"}, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "draft"
    appr = _line(db, po_a)
    assert appr["status"] == "rejected" and appr["comment"] == "금액 확인 필요"
    assert appr["doc_status"] == "rejected"
    log = db.execute(
        "SELECT 1 FROM audit_logs WHERE action='po_reject' AND target_type='po' AND target_id=?", (po_a,)
    ).fetchone()
    assert log is not None


def test_resubmit_after_reject(db, seed, po_a, login):
    mgr = login("a_mgr")
    _confirm(mgr, po_a, seed["a"]["wk"])
    login("a_wk").post(f"/purchase-orders/{po_a}/reject", data={"comment": "x"})
    first = db.execute("SELECT doc_id FROM purchase_orders WHERE id=?", (po_a,)).fetchone()[0]
    assert _confirm(mgr, po_a, seed["a"]["wk"]).status_code == 303
    row = db.execute("SELECT status, doc_id FROM purchase_orders WHERE id=?", (po_a,)).fetchone()
    assert row["status"] == "pending_approval" and row["doc_id"] != first


def _save_pr(c):
    return c.post("/purchase-requisitions/save", data={
        "line_nums": "1", "item_name_1": "테스트품목", "qty_1": "5", "price_1": "1000",
        "request_date": "2026-09-01",
    }, follow_redirects=False)


def test_pr_approval_recorded(db, seed, login):
    mgr = login("a_mgr")
    _save_pr(mgr)
    pr = db.execute("SELECT * FROM purchase_requisitions ORDER BY id DESC LIMIT 1").fetchone()
    mgr.post(f"/purchase-requisitions/{pr['id']}/submit", data={"approver_id": str(seed["a"]["wk"])})
    wk = login("a_wk")
    wk.post(f"/purchase-requisitions/{pr['id']}/reject", data={"comment": "중복 요청"})
    row = db.execute("SELECT status, approved_by, reject_reason FROM purchase_requisitions WHERE id=?", (pr["id"],)).fetchone()
    assert row["status"] == "rejected" and row["approved_by"] == seed["a"]["wk"] and row["reject_reason"] == "중복 요청"


def test_pr_approved_converts_to_po(db, seed, login):
    mgr = login("a_mgr")
    _save_pr(mgr)
    pr = db.execute("SELECT * FROM purchase_requisitions ORDER BY id DESC LIMIT 1").fetchone()
    mgr.post(f"/purchase-requisitions/{pr['id']}/submit", data={"approver_id": str(seed["a"]["wk"])})
    r = login("a_wk").post(f"/purchase-requisitions/{pr['id']}/approve", follow_redirects=False)
    assert r.status_code == 303
    row = db.execute("SELECT status, approved_by FROM purchase_requisitions WHERE id=?", (pr["id"],)).fetchone()
    assert row["status"] == "approved" and row["approved_by"] == seed["a"]["wk"]


def test_pr_staff_cannot_approve_without_designation(db, seed, login):
    # platform_staff가 구매요청 결재선에 없으면 승인/반려 모두 불가
    mgr = login("a_mgr")
    _save_pr(mgr)
    pr = db.execute("SELECT * FROM purchase_requisitions ORDER BY id DESC LIMIT 1").fetchone()
    mgr.post(f"/purchase-requisitions/{pr['id']}/submit", data={"approver_id": str(seed["a"]["wk"])})
    staff = login("t_staff")
    assert staff.post(f"/purchase-requisitions/{pr['id']}/approve", follow_redirects=False).status_code == 403
    assert staff.post(f"/purchase-requisitions/{pr['id']}/reject", data={"comment": "x"}, follow_redirects=False).status_code == 403
    assert db.execute("SELECT status FROM purchase_requisitions WHERE id=?", (pr["id"],)).fetchone()["status"] == "submitted"


def test_staff_cannot_approve_po_without_deputy(db, seed, po_a, login):
    login("a_mgr").post(f"/purchase-orders/{po_a}/confirm", data={"approver_id": str(seed["a"]["wk"])})
    r = login("t_staff").post(f"/purchase-orders/{po_a}/approve", follow_redirects=False)
    assert r.status_code == 403
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "pending_approval"
