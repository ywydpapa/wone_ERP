import pytest

from core.approval import ON_REJECT
from core.constants import ERP_DOC_TYPES, ERP_LEGACY_REDIRECTS
from core.tz import today_kst
from tests.conftest import _user


@pytest.fixture
def dep(db, seed):
    cid = seed["a"]["company"]
    uid = _user(db, "a_dep", "worker", "가대결자")
    db.execute("INSERT INTO employees (user_id, name, company_id) VALUES (?,?,?)", (uid, "가대결자", cid))
    db.commit()
    return uid


def _draft(c, lines, title="대결 테스트"):
    data = {"doc_type": "draft", "title": title, "content": "본문", "save_mode": "submit",
            "line_role": [r for r, _ in lines], "line_user": [str(u) for _, u in lines]}
    return c.post("/api/erp_docs", data=data, follow_redirects=False)


def _doc(db, title="대결 테스트"):
    return db.execute("SELECT * FROM erp_docs WHERE title=? ORDER BY id DESC", (title,)).fetchone()


def test_assign_same_company_only(db, seed, dep, login):
    wk = login("a_wk")
    today = today_kst().isoformat()
    cross = wk.post("/approval-deputies", data={
        "deputy_id": str(seed["b"]["wk"]), "start_date": today, "end_date": today,
    }, follow_redirects=False)
    assert cross.status_code == 400
    assert db.execute("SELECT COUNT(*) FROM approval_deputies").fetchone()[0] == 0

    ok = wk.post("/approval-deputies", data={
        "deputy_id": str(dep), "start_date": today, "end_date": today,
    }, follow_redirects=False)
    assert ok.status_code == 303
    row = db.execute(
        "SELECT * FROM approval_deputies WHERE user_id=? AND deputy_id=?", (seed["a"]["wk"], dep)
    ).fetchone()
    assert row is not None

    cancel = wk.post(f"/approval-deputies/{row['id']}/cancel", follow_redirects=False)
    assert cancel.status_code == 303
    assert db.execute("SELECT COUNT(*) FROM approval_deputies").fetchone()[0] == 0


def test_deputy_can_act_within_period(db, seed, dep, login):
    today = today_kst().isoformat()
    login("a_wk").post("/approval-deputies", data={"deputy_id": str(dep), "start_date": today, "end_date": today})
    _draft(login("a_mgr"), [("결재", seed["a"]["wk"])])
    doc = _doc(db)["id"]

    r = login("a_dep").post(f"/api/erp_docs/{doc}/approve", follow_redirects=False)
    assert r.json()["new_status"] == "done"
    line = db.execute("SELECT approver_id, acted_by FROM approval_lines WHERE doc_id=? AND step=1", (doc,)).fetchone()
    assert line["approver_id"] == seed["a"]["wk"] and line["acted_by"] == dep
    body = login("a_mgr").get(f"/erp_doc/{doc}").text
    assert "대결" in body


def test_deputy_outside_period_blocked(db, seed, dep, login):
    login("a_wk").post("/approval-deputies", data={
        "deputy_id": str(dep), "start_date": "2020-01-01", "end_date": "2020-01-02",
    })
    _draft(login("a_mgr"), [("결재", seed["a"]["wk"])], title="기간외 대결")
    doc = _doc(db, "기간외 대결")["id"]
    r = login("a_dep").post(f"/api/erp_docs/{doc}/approve", follow_redirects=False)
    assert r.status_code == 400


def test_drafter_as_deputy_blocked(db, seed, login):
    today = today_kst().isoformat()
    login("a_wk").post("/approval-deputies", data={
        "deputy_id": str(seed["a"]["mgr"]), "start_date": today, "end_date": today,
    })
    assert db.execute("SELECT 1 FROM approval_deputies WHERE deputy_id=?", (seed["a"]["mgr"],)).fetchone()
    _draft(login("a_mgr"), [("결재", seed["a"]["wk"])], title="자기결재")
    doc = _doc(db, "자기결재")["id"]
    r = login("a_mgr").post(f"/api/erp_docs/{doc}/approve", follow_redirects=False)
    assert r.status_code == 400


def test_bad_deputy_date_rejected(seed, dep, login):
    r = login("a_wk").post("/approval-deputies", data={
        "deputy_id": str(dep), "start_date": "2026-13-01", "end_date": "x",
    }, follow_redirects=False)
    assert r.status_code == 400


def test_staff_without_deputy_blocked(db, seed, login):
    _draft(login("a_mgr"), [("결재", seed["a"]["wk"])], title="스태프차단")
    doc = _doc(db, "스태프차단")["id"]
    r = login("t_staff").post(f"/api/erp_docs/{doc}/approve", follow_redirects=False)
    assert r.status_code == 400
    assert _doc(db, "스태프차단")["status"] == "wait"


def test_reject_then_resubmit(db, seed, login):
    wk = login("a_wk")
    _draft(wk, [("결재", seed["a"]["mgr"])], title="재기안 테스트")
    doc = _doc(db, "재기안 테스트")["id"]
    login("a_mgr").post(f"/api/erp_docs/{doc}/reject", data={"comment": "보완 필요"})
    assert _doc(db, "재기안 테스트")["status"] == "rejected"

    assert wk.get(f"/erp_doc/{doc}").text.count("재상신") >= 1

    r = wk.post(f"/api/erp_docs/{doc}/reopen", follow_redirects=False)
    assert r.json()["ok"]
    row = _doc(db, "재기안 테스트")
    assert row["status"] == "draft"
    line = db.execute("SELECT status FROM approval_lines WHERE doc_id=? AND step=1", (doc,)).fetchone()
    assert line["status"] == "pending"
    history = [h["action"] for h in db.execute(
        "SELECT action FROM doc_history WHERE doc_id=? ORDER BY id", (doc,)
    )]
    assert "반려" in history and "재기안" in history

    assert wk.post(f"/api/erp_docs/{doc}/submit").json()["ok"]
    assert _doc(db, "재기안 테스트")["status"] == "wait"


def test_po_leave_accom_pr_resubmit_uses_own_screen(db, seed, login):
    # po/leave/accom/pr은 전용 화면에서 재신청. 범용 재기안 경로는 막힘
    assert {"po", "leave", "accom", "pr"} <= set(ON_REJECT)


def test_groupware_has_no_salary_form(seed, login):
    assert "salary" not in {dtype for dtype, _ in ERP_DOC_TYPES.values()}
    assert ERP_LEGACY_REDIRECTS["new_salary"] == "/mypage/payslip"
    r = login("a_wk").get("/new_salary", follow_redirects=False)
    assert r.headers["location"] == "/mypage/payslip"
