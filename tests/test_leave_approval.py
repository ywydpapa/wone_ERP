from datetime import date, timedelta

import pytest

from core.constants import ERP_DOC_TYPES
from core.leave_accrual import ensure_accrual
from migrate import run_migrations
from tests.conftest import _connect, _user, seed_companies


DAY = (date.today() + timedelta(days=7)).isoformat()


@pytest.fixture
def eid(db, seed):
    eid = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    ensure_accrual(db, eid, date.fromisoformat(DAY).year)
    db.execute("UPDATE leave_accruals SET granted=15, used=0 WHERE employee_id=?", (eid,))
    db.commit()
    return eid


def _apply(login, **extra):
    data = {"leave_type": "annual", "start_date": DAY, "end_date": DAY, "days": "1", **extra}
    return login("a_wk").post("/mypage/leave", data=data, follow_redirects=False)


def _leave(db):
    return db.execute(
        "SELECT lr.*, d.status AS doc_status FROM leave_requests lr LEFT JOIN erp_docs d ON d.id = lr.doc_id "
        "ORDER BY lr.id DESC"
    ).fetchone()


def _used(db, eid):
    return db.execute("SELECT used FROM leave_accruals WHERE employee_id=?", (eid,)).fetchone()[0]


def test_apply_opens_doc_and_notifies(db, seed, eid, login):
    assert _apply(login).status_code == 303
    lr = _leave(db)
    assert lr["status"] == "pending" and lr["doc_status"] == "wait"
    line = db.execute("SELECT approver_id FROM approval_lines WHERE doc_id=? AND step=1", (lr["doc_id"],)).fetchone()
    assert line["approver_id"] == seed["a"]["mgr"]
    assert db.execute(
        "SELECT 1 FROM notifications WHERE user_id=? AND title='결재 요청' AND link=?",
        (seed["a"]["mgr"], f"/erp_doc/{lr['doc_id']}"),
    ).fetchone()


def test_approve_deducts(db, seed, eid, login):
    _apply(login)
    lr = _leave(db)
    assert login("a_mgr").post(f"/client/leave/{lr['id']}/approve", follow_redirects=False).status_code == 303
    lr = _leave(db)
    assert lr["status"] == "approved" and lr["doc_status"] == "done"
    assert lr["approved_by"] == seed["a"]["mgr"]
    assert _used(db, eid) == 1

    login("a_mgr").post(f"/client/leave/{lr['id']}/cancel")
    assert _leave(db)["status"] == "approved"

    login("a_mgr").post(f"/client/leave/{lr['id']}/cancel", data={"reason": "업무 일정 변경"})
    lr = _leave(db)
    assert lr["status"] == "cancelled" and lr["cancel_reason"] == "업무 일정 변경"
    assert _used(db, eid) == 0
    assert db.execute(
        "SELECT 1 FROM notifications WHERE user_id=? AND title='휴가 취소'", (seed["a"]["wk"],)
    ).fetchone()


def _approved(db, login):
    _apply(login)
    lr = _leave(db)
    login("a_mgr").post(f"/client/leave/{lr['id']}/approve")
    return _leave(db)


def test_hr_cancel_past_ok_confirmed_payroll_blocked(db, seed, eid, login):
    lr = _approved(db, login)
    d = date.fromisoformat(DAY)
    db.execute("INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, total_deduction, net_pay, status) "
               "VALUES (?,?,?,0,0,0,'confirmed')", (eid, d.year, d.month))
    db.commit()
    login("a_mgr").post(f"/client/leave/{lr['id']}/cancel", data={"reason": "정정"})
    assert _leave(db)["status"] == "approved"
    assert _used(db, eid) == 1

    db.execute("DELETE FROM payslips WHERE employee_id=?", (eid,))
    past = (date.today() - timedelta(days=1)).isoformat()
    db.execute("UPDATE leave_requests SET start_date=?, end_date=? WHERE id=?", (past, past, lr["id"]))
    db.commit()
    login("a_mgr").post(f"/client/leave/{lr['id']}/cancel", data={"reason": "당일 출근"})
    assert _leave(db)["status"] == "cancelled"


def test_worker_cannot_cancel_started_leave(db, seed, eid, login):
    lr = _approved(db, login)
    past = (date.today() - timedelta(days=1)).isoformat()
    db.execute("UPDATE leave_requests SET start_date=?, end_date=? WHERE id=?", (past, past, lr["id"]))
    db.commit()
    login("a_wk").post(f"/mypage/leave/{lr['id']}/cancel", data={"reason": "출근함"})
    assert not _leave(db)["cancel_doc_id"]


def test_worker_cancel_request_flow(db, seed, eid, login):
    lr = _approved(db, login)
    wk = login("a_wk")
    wk.post(f"/mypage/leave/{lr['id']}/cancel", data={"reason": "개인 사정"})
    lr = _leave(db)
    assert lr["status"] == "approved" and lr["cancel_doc_id"]
    cdoc = db.execute("SELECT * FROM erp_docs WHERE id=?", (lr["cancel_doc_id"],)).fetchone()
    assert cdoc["doc_type"] == "leave_cancel" and cdoc["status"] == "wait"

    r = wk.post(f"/mypage/leave/{lr['id']}/cancel", data={"reason": "중복"}, follow_redirects=False)
    assert "notice" in r.headers["location"]
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE doc_type='leave_cancel'").fetchone()[0] == 1

    assert login("a_mgr").post(f"/api/erp_docs/{cdoc['id']}/approve").json()["new_status"] == "done"
    lr = _leave(db)
    assert lr["status"] == "cancelled" and lr["cancel_reason"] == "개인 사정"
    assert _used(db, eid) == 0


def test_worker_cancel_request_rejected_keeps_leave(db, seed, eid, login):
    lr = _approved(db, login)
    login("a_wk").post(f"/mypage/leave/{lr['id']}/cancel", data={"reason": "개인 사정"})
    cdoc_id = _leave(db)["cancel_doc_id"]
    login("a_mgr").post(f"/api/erp_docs/{cdoc_id}/reject", data={"comment": "대체 인력 없음"})
    assert _leave(db)["status"] == "approved"
    assert _used(db, eid) == 1
    assert "취소 반려" in login("a_wk").get("/mypage/leave").text


def test_worker_cancel_needs_reason(db, seed, eid, login):
    lr = _approved(db, login)
    login("a_wk").post(f"/mypage/leave/{lr['id']}/cancel", data={"reason": " "})
    assert not _leave(db)["cancel_doc_id"]


def test_approve_from_approval_box(db, seed, eid, login):
    _apply(login)
    doc_id = _leave(db)["doc_id"]
    mgr = login("a_mgr")
    assert "휴가신청" in mgr.get("/approvals?box=wait").text
    assert mgr.post(f"/api/erp_docs/{doc_id}/approve").json()["new_status"] == "done"
    assert _leave(db)["status"] == "approved"
    assert _used(db, eid) == 1


def test_reject_keeps_balance(db, seed, eid, login):
    _apply(login)
    lr = _leave(db)
    login("a_mgr").post(f"/client/leave/{lr['id']}/reject", data={"reason": "인원 부족"})
    lr = _leave(db)
    assert lr["status"] == "rejected" and lr["doc_status"] == "rejected"
    assert lr["reject_reason"] == "인원 부족"
    assert _used(db, eid) == 0
    assert "인원 부족" in login("a_wk").get("/mypage/leave").text


def test_withdraw_keeps_balance(db, seed, eid, login):
    _apply(login)
    lr = _leave(db)
    login("a_wk").post(f"/mypage/leave/{lr['id']}/cancel")
    lr = _leave(db)
    assert lr["status"] == "cancelled" and lr["doc_status"] == "withdrawn"
    assert login("a_mgr").post(f"/client/leave/{lr['id']}/approve", follow_redirects=False).status_code == 403
    assert _used(db, eid) == 0


def test_other_company_404(db, seed, eid, login):
    _apply(login)
    lr = _leave(db)
    b = login("b_mgr")
    assert b.post(f"/client/leave/{lr['id']}/approve", follow_redirects=False).status_code == 404
    assert b.post(f"/api/erp_docs/{lr['doc_id']}/approve").status_code == 404
    assert _leave(db)["status"] == "pending"


def test_multiple_hr_choose(db, seed, eid, login):
    hr2 = _user(db, "a_hr2", "client", "가테스트인사")
    db.execute("INSERT INTO client_users (user_id, company_id, client_role) VALUES (?,?,'hr')", (hr2, seed["a"]["company"]))
    db.commit()
    assert 'name="approver_id"' in login("a_wk").get("/mypage/leave").text
    r = _apply(login)
    assert "error=" in r.headers["location"]
    assert _leave(db) is None

    _apply(login, approver_id=str(hr2))
    lr = _leave(db)
    assert db.execute("SELECT approver_id FROM approval_lines WHERE doc_id=? AND step=1", (lr["doc_id"],)).fetchone()[0] == hr2
    assert login("a_mgr").post(f"/client/leave/{lr['id']}/approve", follow_redirects=False).status_code == 403


def test_preset_line(db, seed, eid, login):
    w2 = _user(db, "a_w2", "worker", "a_w2")
    db.execute("INSERT INTO employees (user_id, name, company_id) VALUES (?,?,?)", (w2, "a_w2", seed["a"]["company"]))
    db.commit()
    login("a_mgr").post("/approval-lines/leave", data={"line_role": ["결재", "결재"],
                                                      "line_user": [str(w2), str(seed["a"]["mgr"])]})
    _apply(login)
    lr = _leave(db)
    assert login("a_mgr").post(f"/client/leave/{lr['id']}/approve", follow_redirects=False).status_code == 403
    login("a_w2").post(f"/api/erp_docs/{lr['doc_id']}/approve")
    assert _leave(db)["status"] == "pending"
    login("a_mgr").post(f"/client/leave/{lr['id']}/approve")
    assert _leave(db)["status"] == "approved"
    assert _used(db, eid) == 1


def test_accommodation_flow(db, seed, login):
    login("a_wk").post("/mypage/accommodation", data={"category": "근로지원인", "title": "근로지원인 요청"})
    req = db.execute("SELECT * FROM accommodation_requests ORDER BY id DESC").fetchone()
    doc = db.execute("SELECT doc_type, status FROM erp_docs WHERE id=?", (req["doc_id"],)).fetchone()
    assert req["status"] == "pending" and doc["doc_type"] == "accom" and doc["status"] == "wait"
    assert db.execute("SELECT 1 FROM notifications WHERE user_id=? AND title='결재 요청'", (seed["a"]["mgr"],)).fetchone()

    assert login("b_mgr").post(f"/client/accommodation/{req['id']}/approve", follow_redirects=False).status_code == 404
    login("a_mgr").post(f"/client/accommodation/{req['id']}/reject", data={"reason": "예산 초과"})
    req = db.execute("SELECT * FROM accommodation_requests WHERE id=?", (req["id"],)).fetchone()
    assert req["status"] == "rejected" and req["review_notes"] == "예산 초과"
    assert req["reviewed_by"] == seed["a"]["mgr"]


def test_groupware_has_no_leave_form(seed, login):
    assert "leave" not in {dtype for dtype, _ in ERP_DOC_TYPES.values()}
    wk = login("a_wk")
    r = wk.get("/new_leave", follow_redirects=False)
    assert r.headers["location"] == "/mypage/leave"
    r = wk.post("/api/erp_docs", data={"doc_type": "leave", "title": "휴가", "line_role": ["결재"],
                                       "line_user": [str(seed["a"]["mgr"])]})
    assert r.status_code == 400


def test_migration_attaches_pending(tmp_path):
    path = str(tmp_path / "m.db")
    run_migrations(path, upto=104)
    conn = _connect(path)
    ids = seed_companies(conn)
    eid = conn.execute("SELECT id FROM employees WHERE user_id=?", (ids["a"]["wk"],)).fetchone()[0]
    lid = conn.execute(
        "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, status) "
        "VALUES (?, 'annual', ?, ?, 1, 'pending')", (eid, DAY, DAY)
    ).lastrowid
    po = conn.execute(
        "INSERT INTO purchase_orders (po_number, po_date, status, company_id) VALUES ('PO-M-1', ?, 'pending_approval', ?)",
        (DAY, ids["a"]["company"]),
    ).lastrowid
    conn.commit()
    conn.close()

    run_migrations(path)
    conn = _connect(path)
    lr = conn.execute("SELECT doc_id FROM leave_requests WHERE id=?", (lid,)).fetchone()
    line = conn.execute("SELECT approver_id, status FROM approval_lines WHERE doc_id=? AND step=1", (lr["doc_id"],)).fetchone()
    assert line["approver_id"] == ids["a"]["mgr"] and line["status"] == "pending"
    assert conn.execute("SELECT status FROM purchase_orders WHERE id=?", (po,)).fetchone()[0] == "draft"
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='approvals'").fetchone()
    conn.close()
