from core import books
from core.tz import now_kst
from tests.conftest import csrf


def _post(db, seed, uid, mgr):
    return books.post(db, seed["a"]["company"], uid, "2026-09-15",
                      [{"code": "813", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}],
                      "테스트전표", "manual")


def test_bulk_copy_creates_drafts(db, seed, login):
    doc = _post(db, seed, seed["a"]["wk"], seed["a"]["mgr"])
    db.commit()
    c = login("a_wk")
    r = c.post("/api/slip/bulk-copy", data={"csrf_token": csrf(c), "doc_ids": str(doc)})
    assert r.status_code == 200 and r.json()["created"] == 0  # 결재선 없는 전표는 생략


def test_bulk_copy_with_approval_lines(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/slip", data={
        "csrf_token": csrf(c), "title": "원본", "slip_type": "대체", "slip_date": "2026-09-15",
        "reviewer_id": str(seed["a"]["mgr"]), "approver_id": str(seed["a"]["mgr"]), "save_mode": "submit",
        "line_count": "1,2", "account_code_1": "813", "debit_1": "500", "credit_1": "0", "partner_id_1": "",
        "account_code_2": "103", "debit_2": "0", "credit_2": "500", "partner_id_2": "",
    }, follow_redirects=False)
    doc = db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    before = db.execute("SELECT COUNT(*) FROM erp_docs").fetchone()[0]
    r = c.post("/api/slip/bulk-copy", data={"csrf_token": csrf(c), "doc_ids": str(doc)})
    assert r.status_code == 200 and r.json()["created"] == 1
    after = db.execute("SELECT COUNT(*) FROM erp_docs").fetchone()[0]
    assert after == before + 1
    copy = db.execute("SELECT * FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()
    assert copy["status"] == "draft" and copy["title"].startswith("[복사]")
    lines = db.execute("SELECT SUM(debit), SUM(credit) FROM slip_lines WHERE doc_id=?", (copy["id"],)).fetchone()
    assert lines[0] == lines[1] == 500


def test_bulk_copy_blocked_when_period_closed(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/slip", data={
        "csrf_token": csrf(c), "title": "원본", "slip_type": "대체", "slip_date": "2026-09-15",
        "reviewer_id": str(seed["a"]["mgr"]), "approver_id": str(seed["a"]["mgr"]), "save_mode": "submit",
        "line_count": "1,2", "account_code_1": "813", "debit_1": "500", "credit_1": "0", "partner_id_1": "",
        "account_code_2": "103", "debit_2": "0", "credit_2": "500", "partner_id_2": "",
    }, follow_redirects=False)
    doc = db.execute("SELECT id FROM erp_docs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    today = now_kst()
    db.execute("INSERT INTO fi_closings (company_id, year, month, status) VALUES (?,?,?,'closed')",
              (seed["a"]["company"], today.year, today.month))
    db.commit()
    before = db.execute("SELECT COUNT(*) FROM erp_docs").fetchone()[0]
    r = c.post("/api/slip/bulk-copy", data={"csrf_token": csrf(c), "doc_ids": str(doc)})
    assert r.status_code == 400
    assert "마감" in r.json()["error"]
    assert db.execute("SELECT COUNT(*) FROM erp_docs").fetchone()[0] == before


def test_bulk_reverse_done_slips(db, seed, login):
    doc = _post(db, seed, seed["a"]["wk"], seed["a"]["mgr"])
    db.commit()
    c = login("a_mgr")
    r = c.post("/api/slip/bulk-reverse", data={"csrf_token": csrf(c), "doc_ids": str(doc), "slip_date": "2026-09-16"})
    assert r.status_code == 200
    body = r.json()
    assert body["reversed"] == 1 and body["failed"] == 0
    assert db.execute("SELECT COUNT(*) FROM erp_docs WHERE reversal_of=?", (doc,)).fetchone()[0] == 1


def test_bulk_reverse_forbidden_for_worker(db, seed, login):
    doc = _post(db, seed, seed["a"]["wk"], seed["a"]["mgr"])
    db.commit()
    c = login("a_wk")
    r = c.post("/api/slip/bulk-reverse", data={"csrf_token": csrf(c), "doc_ids": str(doc), "slip_date": "2026-09-16"})
    assert r.status_code == 403


def test_excel_with_ids_filters_selection(db, seed, login):
    doc1 = _post(db, seed, seed["a"]["wk"], seed["a"]["mgr"])
    doc2 = _post(db, seed, seed["a"]["wk"], seed["a"]["mgr"])
    db.commit()
    c = login("a_wk")
    r = c.get(f"/slip_list/excel?ids={doc1}")
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert text.count("테스트전표") == 1


def test_slip_list_tab_counts(db, seed, login):
    books.post(db, seed["a"]["company"], seed["a"]["wk"], "2026-09-15",
              [{"code": "813", "debit": 500, "credit": 0}, {"code": "103", "debit": 0, "credit": 500}],
              "완료전표", "manual")
    db.commit()
    c = login("a_wk")
    r = c.post("/api/slip", data={
        "csrf_token": csrf(c), "title": "대기전표", "slip_type": "대체", "slip_date": "2026-09-15",
        "reviewer_id": str(seed["a"]["mgr"]), "approver_id": str(seed["a"]["mgr"]), "save_mode": "submit",
        "line_count": "1,2", "account_code_1": "813", "debit_1": "500", "credit_1": "0", "partner_id_1": "",
        "account_code_2": "103", "debit_2": "0", "credit_2": "500", "partner_id_2": "",
    })
    html = c.get("/slip_list").text
    assert "전체" in html and "임시저장" in html and "대기" in html and "반려" in html and "완료" in html
