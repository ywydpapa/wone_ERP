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


def test_submit_binds_designated_approver(db, seed, po_a, login):
    c = login("a_mgr")
    r = _confirm(c, po_a, seed["a"]["wk"])
    assert r.status_code == 303
    row = db.execute(
        "SELECT status FROM purchase_orders WHERE id=?", (po_a,)
    ).fetchone()
    assert row["status"] == "pending_approval"
    appr = db.execute(
        "SELECT approver_id, status FROM approvals WHERE doc_type='po' AND doc_id=?", (po_a,)
    ).fetchone()
    assert appr["approver_id"] == seed["a"]["wk"]
    assert appr["status"] == "pending"


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
    assert r.status_code in (400, 404)
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
    appr = db.execute("SELECT status, approver_id FROM approvals WHERE doc_type='po' AND doc_id=?", (po_a,)).fetchone()
    assert appr["status"] == "approved" and appr["approver_id"] == seed["a"]["wk"]
    log = db.execute(
        "SELECT 1 FROM audit_logs WHERE action='po_approve' AND target_type='po' AND target_id=?", (po_a,)
    ).fetchone()
    assert log is not None


def test_client_can_approve_on_behalf_of_designated_worker(db, seed, po_a, login):
    # 지정 결재자가 아니어도 고객사 담당자는 대행 승인 가능
    login("a_mgr").post(f"/purchase-orders/{po_a}/confirm", data={"approver_id": str(seed["a"]["wk"])})
    r = login("a_mgr").post(f"/purchase-orders/{po_a}/approve", follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "confirmed"
    appr = db.execute("SELECT approver_id FROM approvals WHERE doc_type='po' AND doc_id=?", (po_a,)).fetchone()
    assert appr["approver_id"] == seed["a"]["wk"]
    log = db.execute(
        "SELECT user_id FROM audit_logs WHERE action='po_approve' AND target_type='po' AND target_id=?", (po_a,)
    ).fetchone()
    assert log["user_id"] == seed["a"]["mgr"]


def test_designated_approver_can_reject(db, seed, po_a, login):
    login("a_mgr").post(f"/purchase-orders/{po_a}/confirm", data={"approver_id": str(seed["a"]["wk"])})
    r = login("a_wk").post(f"/purchase-orders/{po_a}/reject", data={"comment": "금액 확인 필요"}, follow_redirects=False)
    assert r.status_code == 303
    assert db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_a,)).fetchone()["status"] == "draft"
    appr = db.execute("SELECT status, comment FROM approvals WHERE doc_type='po' AND doc_id=?", (po_a,)).fetchone()
    assert appr["status"] == "rejected" and appr["comment"] == "금액 확인 필요"
    log = db.execute(
        "SELECT 1 FROM audit_logs WHERE action='po_reject' AND target_type='po' AND target_id=?", (po_a,)
    ).fetchone()
    assert log is not None
