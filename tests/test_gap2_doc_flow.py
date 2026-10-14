import hashlib

import pytest


@pytest.fixture
def a_ref(db, seed):
    # 참조자로 지정할 a사 소속의 또 다른 근로자
    pw = hashlib.sha256(b"1234").hexdigest()
    uid = db.execute(
        "INSERT INTO users (username, password, name, role) VALUES ('a_ref',?,?,'worker')",
        (pw, "가테스트참조"),
    ).lastrowid
    db.execute(
        "INSERT INTO employees (user_id, name, company_id) VALUES (?,?,?)",
        (uid, "가테스트참조", seed["a"]["company"]),
    )
    db.commit()
    return uid


def _create(login, a_ref, seed):
    return login("a_wk").post("/api/erp_docs", data={
        "doc_type": "draft", "title": "결재 테스트 문서", "content": "본문",
        "line_role": ["결재", "참조"], "line_user": [str(seed["a"]["mgr"]), str(a_ref)],
    }, follow_redirects=False)


def test_create_submit_notifies_approver_and_logs_audit(db, seed, login, a_ref):
    r = _create(login, a_ref, seed)
    assert r.status_code == 303
    doc = db.execute("SELECT id, company_id FROM erp_docs WHERE title='결재 테스트 문서'").fetchone()

    notif = db.execute(
        "SELECT title, message, link FROM notifications WHERE user_id=?", (seed["a"]["mgr"],)
    ).fetchall()
    assert len(notif) == 1
    assert notif[0]["title"] == "결재 요청"
    assert notif[0]["message"] == "결재 테스트 문서"
    assert notif[0]["link"] == f"/erp_doc/{doc['id']}"

    log = db.execute(
        "SELECT summary, company_id FROM audit_logs WHERE action='doc_submit' AND target_type='doc' AND target_id=?",
        (doc["id"],)
    ).fetchone()
    assert log is not None
    assert log["summary"].endswith("결재 테스트 문서")
    assert log["company_id"] == doc["company_id"]


def test_approve_notifies_author_and_refs(db, seed, login, a_ref):
    r = _create(login, a_ref, seed)
    doc_id = db.execute("SELECT id FROM erp_docs WHERE title='결재 테스트 문서'").fetchone()["id"]

    r = login("a_mgr").post(f"/api/erp_docs/{doc_id}/approve", follow_redirects=False)
    assert r.json()["new_status"] == "done"

    author_notif = db.execute(
        "SELECT title FROM notifications WHERE user_id=? AND title='결재 완료'", (seed["a"]["wk"],)
    ).fetchone()
    assert author_notif is not None

    ref_notif = db.execute(
        "SELECT title FROM notifications WHERE user_id=? AND title='결재 완료(참조)'", (a_ref,)
    ).fetchone()
    assert ref_notif is not None

    log = db.execute(
        "SELECT 1 FROM audit_logs WHERE action='doc_approve' AND target_type='doc' AND target_id=?", (doc_id,)
    ).fetchone()
    assert log is not None


def test_reject_notifies_author(db, seed, login, a_ref):
    _create(login, a_ref, seed)
    doc_id = db.execute("SELECT id FROM erp_docs WHERE title='결재 테스트 문서'").fetchone()["id"]

    r = login("a_mgr").post(f"/api/erp_docs/{doc_id}/reject", data={"comment": "보류"}, follow_redirects=False)
    assert r.json()["ok"] is True

    notif = db.execute(
        "SELECT title FROM notifications WHERE user_id=? AND title='결재 반려'", (seed["a"]["wk"],)
    ).fetchone()
    assert notif is not None

    log = db.execute(
        "SELECT 1 FROM audit_logs WHERE action='doc_reject' AND target_type='doc' AND target_id=?", (doc_id,)
    ).fetchone()
    assert log is not None


def test_new_leave_redirects_to_mypage(login):
    r = login("a_wk").get("/new_leave", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/mypage/leave"


def test_erp_doc_print_route_removed(db, seed, login, a_ref):
    _create(login, a_ref, seed)
    doc_id = db.execute("SELECT id FROM erp_docs WHERE title='결재 테스트 문서'").fetchone()["id"]
    r = login("a_wk").get(f"/erp_doc/{doc_id}/print", follow_redirects=False)
    assert r.status_code == 404
