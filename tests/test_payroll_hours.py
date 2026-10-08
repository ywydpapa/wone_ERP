from core.attendance import calc_night_minutes, get_month_work_stats
from core.work_schedule import calc_work_minutes, get_schedule


def test_night_minutes_same_day():
    # 20:00~23:00 근무, 22:00~23:00 1시간만 야간
    assert calc_night_minutes("20:00", "23:00") == 60


def test_night_minutes_no_overlap():
    assert calc_night_minutes("09:00", "18:00") == 0


def test_night_minutes_overnight_full_window():
    # 22:00 출근 ~ 익일 06:00 퇴근, 야간시간대 전체 포함
    assert calc_night_minutes("22:00", "06:00") == 480


def test_night_minutes_overnight_partial():
    # 23:00 출근 ~ 익일 05:00 퇴근 = 6시간 전부 야간
    assert calc_night_minutes("23:00", "05:00") == 360


def test_work_minutes_overnight():
    sched = {"start_time": "22:00", "end_time": "06:00", "break_min": 60}
    work_m, ot_m = calc_work_minutes("22:00", "06:00", sched)
    assert work_m == 420  # 8시간 - 휴게 1시간
    assert ot_m == 0


def test_work_minutes_overnight_with_overtime():
    sched = {"start_time": "22:00", "end_time": "06:00", "break_min": 60}
    work_m, ot_m = calc_work_minutes("22:00", "07:30", sched)
    assert work_m == 510  # 9.5시간 - 휴게 1시간
    assert ot_m == 90  # 06:00 이후 1.5시간 연장


def test_schedule_default_rest_off_day():
    sched = get_schedule(None, None)
    assert sched["rest_day"] == 6  # 일요일
    assert sched["off_day"] == 5  # 토요일


def test_month_work_stats_custom_rest_day(db):
    cid = db.execute("INSERT INTO client_companies (name) VALUES ('테스트회사')").lastrowid
    # 월요일을 주휴일로 지정
    db.execute(
        "UPDATE work_schedules SET rest_day=0, off_day=6 WHERE company_id=?", (cid,)
    )
    eid = db.execute(
        "INSERT INTO employees (name, company_id, status) VALUES ('근로자', ?, 'active')", (cid,)
    ).lastrowid

    # 2026-09월: 09-07(월)=주휴일 근무, 09-13(일)=무급휴무일 근무
    db.execute(
        "INSERT INTO attendance (employee_id, work_date, clock_in, clock_out, work_minutes, status) "
        "VALUES (?, '2026-09-07', '09:00', '18:00', 480, 'normal')", (eid,)
    )
    db.execute(
        "INSERT INTO attendance (employee_id, work_date, clock_in, clock_out, work_minutes, status) "
        "VALUES (?, '2026-09-13', '09:00', '18:00', 480, 'normal')", (eid,)
    )
    db.commit()

    stats = get_month_work_stats(db, eid, "2026-09")
    # 주휴일(월) 근무만 휴일 집계, 무급휴무일(일) 근무는 휴일 집계에서 제외
    assert stats["holiday_mins"] == 480
    assert stats["total_mins"] == 960


def test_month_work_stats_workers_day_counts_as_holiday(db):
    cid = db.execute("INSERT INTO client_companies (name) VALUES ('테스트회사2')").lastrowid
    eid = db.execute(
        "INSERT INTO employees (name, company_id, status) VALUES ('근로자2', ?, 'active')", (cid,)
    ).lastrowid
    db.execute(
        "INSERT INTO attendance (employee_id, work_date, clock_in, clock_out, work_minutes, status) "
        "VALUES (?, '2026-05-01', '09:00', '18:00', 480, 'normal')", (eid,)
    )
    db.commit()

    stats = get_month_work_stats(db, eid, "2026-05")
    assert stats["holiday_mins"] == 480
