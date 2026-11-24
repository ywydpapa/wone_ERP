import pathlib


def test_job_attachment(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/jobs", data={"workDate": "2026-10-24", "workTitle": "첨부일지"},
               files={"workAttachment": ("memo.txt", b"hello", "text/plain")}, follow_redirects=False)
    assert r.status_code == 303
    jid, att = db.execute("SELECT id, attachment FROM jobs WHERE title='첨부일지'").fetchone()
    name, _, saved = att.partition("|")
    assert name == "memo.txt"
    assert "memo.txt" in c.get(f"/job/{jid}").text
    assert c.get(f"/files/jobs/{saved}").content == b"hello"
    pathlib.Path("var/uploads/jobs", saved).unlink()


def test_job_attachment_bad_ext(db, seed, login):
    r = login("a_wk").post("/api/jobs", data={"workDate": "2026-10-24", "workTitle": "확장자"},
                           files={"workAttachment": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
    assert not db.execute("SELECT 1 FROM jobs WHERE title='확장자'").fetchone()
