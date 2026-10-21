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


def test_missing_clockout_row_is_appeal_eligible(db, seed, login):
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


def test_hr_approve_applies_desired_times_for_absent(db, seed, login):
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


def test_hr_approve_late_without_desired_times_keeps_existing_behavior(db, seed, login):
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
