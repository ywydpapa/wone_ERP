def test_overtime_approval_updates_attendance(db, seed, login):
    wk = login("a_wk")
    data = {
        "doc_type": "overtime", "title": "초과근무신청", "content": "마감 대응", "save_mode": "submit",
        "line_role": ["결재"], "line_user": [str(seed["a"]["mgr"])],
        "work_date": "2026-09-10", "ot_minutes": "90",
    }
    wk.post("/api/erp_docs", data=data, follow_redirects=False)
    doc = db.execute("SELECT * FROM erp_docs WHERE title='초과근무신청' ORDER BY id DESC").fetchone()
    login("a_mgr").post(f"/api/erp_docs/{doc['id']}/approve")

    emp_id = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    row = db.execute(
        "SELECT overtime_minutes FROM attendance WHERE employee_id=? AND work_date='2026-09-10'", (emp_id,)
    ).fetchone()
    assert row["overtime_minutes"] == 90


def test_overtime_rejected_does_not_touch_attendance(db, seed, login):
    wk = login("a_wk")
    data = {
        "doc_type": "overtime", "title": "초과근무반려", "content": "마감 대응", "save_mode": "submit",
        "line_role": ["결재"], "line_user": [str(seed["a"]["mgr"])],
        "work_date": "2026-09-11", "ot_minutes": "60",
    }
    wk.post("/api/erp_docs", data=data, follow_redirects=False)
    doc = db.execute("SELECT * FROM erp_docs WHERE title='초과근무반려' ORDER BY id DESC").fetchone()
    login("a_mgr").post(f"/api/erp_docs/{doc['id']}/reject", data={"comment": "과다"})

    emp_id = db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]
    row = db.execute(
        "SELECT 1 FROM attendance WHERE employee_id=? AND work_date='2026-09-11'", (emp_id,)
    ).fetchone()
    assert row is None
