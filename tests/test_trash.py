def test_trash_lists_own_trashed_jobs(db, seed, login):
    for uid, title, status in ((seed["a"]["wk"], "지운일지", "trash"),
                               (seed["a"]["wk"], "진행일지", "progress"),
                               (seed["b"]["wk"], "남의일지", "trash")):
        db.execute("INSERT INTO jobs (user_id, work_date, title, status) VALUES (?, '2026-10-01', ?, ?)", (uid, title, status))
    db.commit()

    html = login("a_wk").get("/trash").text
    assert "지운일지" in html
    assert "진행일지" not in html
    assert "남의일지" not in html


def test_restore_from_trash(db, seed, login):
    jid = db.execute("INSERT INTO jobs (user_id, work_date, title, status) VALUES (?, '2026-10-01', '복원일지', 'trash')",
                     (seed["a"]["wk"],)).lastrowid
    db.commit()
    c = login("a_wk")
    r = c.post(f"/api/jobs/{jid}/restore", follow_redirects=False)
    assert r.headers["location"] == "/trash"
    assert db.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0] == "progress"
