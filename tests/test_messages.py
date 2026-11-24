def test_send_blocks_other_company(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/messages/send", data={"to_name": "나테스트근로자", "body": "안녕"})
    assert r.status_code == 400
    assert r.json()["error"] == "받는 사람을 찾을 수 없습니다."
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


def test_send_to_same_book_mgr(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/messages/send", data={"to_name": "가테스트담당", "body": "안녕"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


def test_send_to_staff_ok(db, seed, login):
    c = login("a_wk")
    r = c.post("/api/messages/send", data={"to_name": "스태프", "body": "안녕"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_dept_members_excludes_other_company(db, seed, login):
    db.execute("UPDATE users SET dept='인사팀' WHERE id IN (?,?,?)", (seed["a"]["wk"], seed["b"]["wk"], seed["staff"]))
    db.commit()
    r = login("a_wk").get("/api/dept/members", params={"dept": "인사팀"})
    assert r.status_code == 200
    names = [m["name"] for m in r.json()]
    assert "나테스트근로자" not in names
    assert "가테스트근로자" in names
    assert "스태프" in names


def test_reply_sent(db, seed, login):
    c = login("a_wk")
    c.post("/api/messages/send", data={"to_name": "가테스트담당", "body": "안녕"})
    sent = db.execute("SELECT id FROM messages WHERE user_id=? AND direction='out'", (seed["a"]["wk"],)).fetchone()
    c.post(f"/api/messages/{sent['id']}/reply", data={"body": "추가"})
    row = db.execute("SELECT recipient FROM messages WHERE body='추가'").fetchone()
    assert row["recipient"] == "가테스트담당"


def test_reply_delivered(db, seed, login):
    c = login("a_wk")
    c.post("/api/messages/send", data={"to_name": "가테스트담당", "body": "안녕"})
    sent = db.execute("SELECT id FROM messages WHERE user_id=? AND direction='out'", (seed["a"]["wk"],)).fetchone()
    c.post(f"/api/messages/{sent['id']}/reply", data={"body": "추가"})
    row = db.execute("SELECT user_id, sender FROM messages WHERE body='추가' AND direction='in'").fetchone()
    assert row["user_id"] == seed["a"]["mgr"]
    assert row["sender"] == "가테스트근로자"


def test_reply_to_received(db, seed, login):
    login("a_wk").post("/api/messages/send", data={"to_name": "가테스트담당", "body": "안녕"})
    c = login("a_mgr")
    got = db.execute("SELECT id FROM messages WHERE user_id=? AND direction='in'", (seed["a"]["mgr"],)).fetchone()
    c.post(f"/api/messages/{got['id']}/reply", data={"body": "확인"})
    row = db.execute("SELECT user_id FROM messages WHERE body='확인' AND direction='in'").fetchone()
    assert row["user_id"] == seed["a"]["wk"]
