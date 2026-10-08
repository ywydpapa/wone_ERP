import json

import pytest

from tests.conftest import _user


@pytest.fixture
def wks(db, seed):
    cid = seed["a"]["company"]
    ids = {}
    for name in ("a_w2", "a_w3"):
        uid = _user(db, name, "worker", name)
        db.execute("INSERT INTO employees (user_id, name, company_id) VALUES (?,?,?)", (uid, name, cid))
        ids[name] = uid
    db.commit()
    return ids


def _draft(c, lines, title="결재선 테스트", save_mode="submit"):
    data = {"doc_type": "draft", "title": title, "content": "본문", "save_mode": save_mode,
            "line_role": [r for r, _ in lines], "line_user": [str(u) for _, u in lines]}
    return c.post("/api/erp_docs", data=data, follow_redirects=False)


def _doc(db, title="결재선 테스트"):
    return db.execute("SELECT * FROM erp_docs WHERE title=? ORDER BY id DESC", (title,)).fetchone()


def _lines(db, doc_id):
    return {r["approver_id"]: r["status"] for r in db.execute("SELECT * FROM approval_lines WHERE doc_id=?", (doc_id,))}


def test_create_orders_lines(db, seed, wks, login):
    w2, w3, mgr = wks["a_w2"], wks["a_w3"], seed["a"]["mgr"]
    r = _draft(login("a_wk"), [("참조", w3), ("결재", w2), ("후결", mgr)])
    assert r.status_code == 303
    rows = db.execute("SELECT role, approver_id FROM approval_lines WHERE doc_id=? ORDER BY step", (_doc(db)["id"],)).fetchall()
    assert [(x["role"], x["approver_id"]) for x in rows] == [("기안", seed["a"]["wk"]), ("결재", w2), ("후결", mgr), ("참조", w3)]
    assert "csrf_token" not in (_doc(db)["extra_fields"] or "")


def test_rejects_other_company_and_missing_approver(db, seed, wks, login):
    c = login("a_wk")
    assert _draft(c, [("결재", seed["b"]["mgr"])]).status_code == 400
    assert _draft(c, [("참조", wks["a_w2"])]).status_code == 400
    assert _draft(c, [("결재", wks["a_w2"]), ("합의", wks["a_w2"])]).status_code == 400
    assert _doc(db) is None


def test_sequential_order(db, seed, wks, login):
    w2, w3 = wks["a_w2"], wks["a_w3"]
    _draft(login("a_wk"), [("결재", w2), ("결재", w3)])
    doc = _doc(db)["id"]
    c3 = login("a_w3")
    assert c3.post(f"/api/erp_docs/{doc}/approve").status_code == 400
    assert "결재선 테스트" not in c3.get("/approvals?box=wait").text
    assert "결재선 테스트" in c3.get("/approvals?box=upcoming").text

    assert login("a_w2").post(f"/api/erp_docs/{doc}/approve").json()["new_status"] == "progress"
    assert "결재선 테스트" in c3.get("/approvals?box=wait").text
    assert c3.post(f"/api/erp_docs/{doc}/approve").json()["new_status"] == "done"
    assert "결재선 테스트" in c3.get("/approvals?box=done").text


def test_final_skips_rest(db, seed, wks, login):
    w2, w3 = wks["a_w2"], wks["a_w3"]
    _draft(login("a_wk"), [("결재", w2), ("결재", w3)])
    doc = _doc(db)["id"]
    r = login("a_w2").post(f"/api/erp_docs/{doc}/approve", data={"final": "1"})
    assert r.json()["new_status"] == "done"
    assert _lines(db, doc)[w2] == "final"
    assert _lines(db, doc)[w3] == "skipped"
    assert "전결" in login("a_wk").get(f"/erp_doc/{doc}").text


def test_post_approval(db, seed, wks, login):
    w2, w3 = wks["a_w2"], wks["a_w3"]
    _draft(login("a_wk"), [("결재", w2), ("후결", w3)])
    doc = _doc(db)["id"]
    c3 = login("a_w3")
    assert c3.post(f"/api/erp_docs/{doc}/approve").status_code == 400
    assert login("a_w2").post(f"/api/erp_docs/{doc}/approve").json()["new_status"] == "done"
    assert "결재선 테스트" in c3.get("/approvals?box=wait").text
    assert "후결 확인" in c3.get(f"/erp_doc/{doc}").text
    assert c3.post(f"/api/erp_docs/{doc}/approve").json()["ok"]
    assert _lines(db, doc)[w3] == "approved"
    assert "결재선 테스트" not in c3.get("/approvals?box=wait").text


def test_reference_reads_only(db, seed, wks, login):
    w2, w3 = wks["a_w2"], wks["a_w3"]
    _draft(login("a_wk"), [("결재", w2), ("참조", w3)])
    doc = _doc(db)["id"]
    c3 = login("a_w3")
    assert c3.get(f"/erp_doc/{doc}").status_code == 200
    assert db.execute("SELECT acted_at FROM approval_lines WHERE doc_id=? AND approver_id=?", (doc, w3)).fetchone()[0]
    assert c3.post(f"/api/erp_docs/{doc}/approve").status_code == 400
    assert c3.post(f"/api/erp_docs/{doc}/reject", data={"comment": "x"}).status_code == 400
    assert "결재선 테스트" in c3.get("/approvals?box=ref").text
    assert login("a_w2").post(f"/api/erp_docs/{doc}/approve").json()["new_status"] == "done"


def test_withdraw_only_before_first_action(db, seed, wks, login):
    w2, w3 = wks["a_w2"], wks["a_w3"]
    wk = login("a_wk")
    _draft(wk, [("결재", w2), ("결재", w3)])
    doc = _doc(db)["id"]
    assert "결재선 테스트" in wk.get("/approvals?box=sent").text
    login("a_w2").post(f"/api/erp_docs/{doc}/approve")
    assert wk.post(f"/api/erp_docs/{doc}/withdraw").status_code == 400

    _draft(wk, [("결재", w2)], title="회수 문서")
    doc2 = _doc(db, "회수 문서")["id"]
    assert wk.post(f"/api/erp_docs/{doc2}/withdraw").json()["ok"]
    assert "회수 문서" in wk.get("/approvals?box=draft").text


def test_reject_by_current_only(db, seed, wks, login):
    w2, w3 = wks["a_w2"], wks["a_w3"]
    _draft(login("a_wk"), [("합의", w2), ("결재", w3)])
    doc = _doc(db)["id"]
    assert login("a_w3").post(f"/api/erp_docs/{doc}/reject", data={"comment": "x"}).status_code == 400
    assert login("a_w2").post(f"/api/erp_docs/{doc}/reject", data={"comment": "반대"}).json()["ok"]
    assert _doc(db)["status"] == "rejected"
    assert "결재선 테스트" in login("a_wk").get("/approvals?box=rejected").text


def test_preset_prefills_form(db, seed, wks, login):
    w2 = wks["a_w2"]
    mgr = login("a_mgr")
    assert mgr.get("/approval-lines").status_code == 200
    mgr.post("/approval-lines/draft", data={"line_role": ["결재", "참조"], "line_user": [str(w2), str(seed["a"]["wk"])]})
    row = db.execute("SELECT * FROM approval_presets WHERE company_id=? AND form_key='draft'", (seed["a"]["company"],)).fetchone()
    assert json.loads(row["lines"]) == [{"role": "결재", "user": w2}, {"role": "참조", "user": seed["a"]["wk"]}]
    html = login("a_w3").get("/draft_doc").text
    assert f'<option value="{w2}" selected>' in html

    mgr.post("/approval-lines/draft", data={"line_role": ["결재"], "line_user": [""]})
    assert db.execute("SELECT COUNT(*) FROM approval_presets").fetchone()[0] == 0


def test_preset_guards(db, seed, wks, login):
    assert login("a_wk").get("/approval-lines", follow_redirects=False).status_code == 303
    r = login("a_mgr").post("/approval-lines/draft", data={"line_role": ["결재"], "line_user": [str(seed["b"]["mgr"])]})
    assert r.status_code == 400
    assert login("a_mgr").post("/approval-lines/tpl-999", data={}).status_code == 403
