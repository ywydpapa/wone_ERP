from tests.test_mypage_withholding import _make_payslip, _verify


def _emp(db, user_id):
    return db.execute("SELECT id FROM employees WHERE user_id=?", (user_id,)).fetchone()[0]


def _task(db, emp_id, by):
    db.execute("INSERT INTO tasks (title, task_type, assigned_to, assigned_by) VALUES ('입력', 'data', ?, ?)", (emp_id, by))
    db.commit()


def test_manager_is_latest_assigner(db, seed, login):
    emp = _emp(db, seed["a"]["wk"])
    _task(db, emp, seed["staff"])
    _task(db, emp, seed["a"]["mgr"])
    r = login("a_wk").get("/api/messages/manager")
    assert r.status_code == 200
    assert r.json() == {"name": "가테스트담당"}


def test_manager_none(db, seed, login):
    assert login("a_wk").get("/api/messages/manager").status_code == 404


def test_contacts_same_book_only(db, seed, login):
    names = login("a_wk").get("/api/messages/contacts").json()
    assert "가테스트담당" in names
    assert "스태프" in names
    assert "나테스트근로자" not in names
    assert "가테스트근로자" not in names


def test_payslip_defaults_to_latest(db, seed, login):
    emp = _emp(db, seed["a"]["wk"])
    _make_payslip(db, seed["a"]["company"], emp, 2025, 3, {"BASE": 2000000}, pay_date="2025-03-25")
    _make_payslip(db, seed["a"]["company"], emp, 2025, 4, {"BASE": 2100000}, pay_date="2025-04-25")
    c = login("a_wk")
    _verify(db, c, seed["a"]["wk"], next="/mypage/payslip")
    html = c.get("/mypage/payslip").text
    assert 'data-pay-ym="2025-04"' in html
    assert 'data-net="' in html
    assert 'data-pay-ym="2025-03"' in c.get("/mypage/payslip?year=2025&month=3").text


def test_worker_voice_script_only_for_worker(db, seed, login):
    assert "worker-voice.js" in login("a_wk").get("/mypage").text
    assert "worker-voice.js" not in login("a_mgr").get("/").text


def test_message_list_voice_items(db, seed, login):
    c = login("a_wk")
    c.post("/api/messages/send", data={"to_name": "가테스트담당", "body": "출근했습니다"})
    login("a_mgr").post("/api/messages/send", data={"to_name": "가테스트근로자", "body": "확인했어요"})
    html = c.get("/newarrived_jobs").text
    assert 'data-voice-text="새 메시지, 가테스트담당, 확인했어요"' in html
    assert 'data-voice-text="받는 사람 가테스트담당, 출근했습니다"' in html
