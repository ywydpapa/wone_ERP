def _emp_a(db, seed):
    return db.execute("SELECT id FROM employees WHERE user_id=?", (seed["a"]["wk"],)).fetchone()[0]


def test_absent_row_is_appeal_eligible(db, seed, login):
    emp = _emp_a(db, seed)
    att_id = db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, notes) VALUES (?, '2026-09-10', 'absent', '근태마감')",
        (emp,),
    ).lastrowid
    db.commit()

    c = login("a_wk")
    r = c.get(f"/mypage/attendance/{att_id}/appeal")
    assert r.status_code == 200
    assert "결근" in r.text

    r = c.post(f"/mypage/attendance/{att_id}/appeal", data={
        "appeal_type": "etc", "appeal_reason": "실제로는 출근함",
        "desired_clock_in": "09:00", "desired_clock_out": "18:00",
    }, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT * FROM attendance WHERE id=?", (att_id,)).fetchone()
    assert row["appeal"] == "pending"
    assert row["appeal_desired_clock_in"] == "09:00"
    assert row["appeal_desired_clock_out"] == "18:00"


def test_missing_clockout_appeal_eligible(db, seed, login):
    emp = _emp_a(db, seed)
    att_id = db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, clock_in, clock_out) "
        "VALUES (?, '2026-09-11', 'normal', '09:00:00', NULL)",
        (emp,),
    ).lastrowid
    db.commit()

    c = login("a_wk")
    r = c.get(f"/mypage/attendance/{att_id}/appeal")
    assert r.status_code == 200
    assert "퇴근 미기록" in r.text


def test_normal_complete_row_not_eligible(db, seed, login):
    emp = _emp_a(db, seed)
    att_id = db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, clock_in, clock_out) "
        "VALUES (?, '2026-09-12', 'normal', '09:00:00', '18:00:00')",
        (emp,),
    ).lastrowid
    db.commit()

    c = login("a_wk")
    r = c.get(f"/mypage/attendance/{att_id}/appeal", follow_redirects=False)
    assert r.status_code == 303


def test_hr_approve_absent_desired_times(db, seed, login):
    emp = _emp_a(db, seed)
    att_id = db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, appeal, appeal_type, "
        "appeal_desired_clock_in, appeal_desired_clock_out) "
        "VALUES (?, '2026-09-10', 'absent', 'pending', 'etc', '09:00', '18:00')",
        (emp,),
    ).lastrowid
    db.commit()

    staff = login("t_staff")
    r = staff.post(f"/hr/attendance/{att_id}/appeal-review", data={"action": "approve"}, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT * FROM attendance WHERE id=?", (att_id,)).fetchone()
    assert row["status"] == "normal"
    assert row["appeal"] == "approved"
    assert row["clock_in"] == "09:00"
    assert row["clock_out"] == "18:00"
    assert row["work_minutes"] > 0


def test_hr_approve_late_status(db, seed, login):
    # 희망시간 미입력이어도 기존 출퇴근시각 유지한 채 승인 처리
    emp = _emp_a(db, seed)
    att_id = db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, clock_in, clock_out, appeal, appeal_type) "
        "VALUES (?, '2026-09-13', 'late', '09:20:00', '18:00:00', 'pending', 'transit')",
        (emp,),
    ).lastrowid
    db.commit()

    staff = login("t_staff")
    r = staff.post(f"/hr/attendance/{att_id}/appeal-review", data={"action": "approve"}, follow_redirects=False)
    assert r.status_code == 303

    row = db.execute("SELECT * FROM attendance WHERE id=?", (att_id,)).fetchone()
    assert row["status"] == "normal"
    assert row["appeal"] == "approved"
    assert row["clock_in"] == "09:20:00"


def test_reject_requires_reason(db, seed, login):
    emp = _emp_a(db, seed)
    att_id = db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, appeal, appeal_type) "
        "VALUES (?, '2026-09-11', 'late', 'pending', 'etc')",
        (emp,),
    ).lastrowid
    db.commit()

    staff = login("t_staff")
    r = staff.post(f"/hr/attendance/{att_id}/appeal-review", data={"action": "reject"}, follow_redirects=False)
    assert r.headers["location"] == f"/hr/attendance/appeals/{att_id}"
    assert db.execute("SELECT appeal FROM attendance WHERE id=?", (att_id,)).fetchone()[0] == "pending"

    staff.post(f"/hr/attendance/{att_id}/appeal-review", data={"action": "reject", "reject_reason": "증빙 없음"})
    row = db.execute("SELECT appeal, appeal_reject_reason FROM attendance WHERE id=?", (att_id,)).fetchone()
    assert row["appeal"] == "rejected" and row["appeal_reject_reason"] == "증빙 없음"


def test_appeal_server_checks(db, seed, login):
    emp = _emp_a(db, seed)
    att_id = db.execute(
        "INSERT INTO attendance (employee_id, work_date, status, notes) VALUES (?, '2026-09-11', 'absent', '근태마감')",
        (emp,),
    ).lastrowid
    db.execute(
        "UPDATE client_companies SET appeal_require_file=1, appeal_types=? "
        "WHERE id=(SELECT company_id FROM employees WHERE id=?)",
        ('["etc"]', emp),
    )
    db.commit()
    c = login("a_wk")
    url = f"/mypage/attendance/{att_id}/appeal"

    r = c.post(url, data={"appeal_type": "etc"}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    r = c.post(url, data={"appeal_type": "disability"}, files={"evidence": ("a.pdf", b"x")}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert db.execute("SELECT appeal FROM attendance WHERE id=?", (att_id,)).fetchone()[0] is None

    r = c.post(url, data={"appeal_type": "etc"}, files={"evidence": ("a.pdf", b"x")}, follow_redirects=False)
    assert r.headers["location"] == "/mypage/attendance"
    assert db.execute("SELECT appeal FROM attendance WHERE id=?", (att_id,)).fetchone()[0] == "pending"

    db.execute("UPDATE attendance SET appeal='approved' WHERE id=?", (att_id,))
    db.commit()
    c.post(url, data={"appeal_type": "etc"}, files={"evidence": ("a.pdf", b"x")})
    assert db.execute("SELECT appeal FROM attendance WHERE id=?", (att_id,)).fetchone()[0] == "approved"
