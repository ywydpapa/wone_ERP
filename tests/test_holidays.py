from core.attendance import build_calendar_data
from core.holiday import get_holidays, is_holiday


def test_workers_day_present_without_seed_row(db):
    holidays = get_holidays(db, 2030)
    dates = {h["date"] for h in holidays}
    assert "2030-05-01" in dates


def test_workers_day_not_duplicated_if_already_seeded(db):
    db.execute(
        "INSERT INTO holidays (year, date, name, type) VALUES (2025, '2025-05-01', '근로자의날', 'public')"
    )
    db.commit()
    holidays = get_holidays(db, 2025)
    dates = [h["date"] for h in holidays if h["date"] == "2025-05-01"]
    assert len(dates) == 1


def test_is_holiday_workers_day_true(db):
    assert is_holiday(db, "2029-05-01") is True


def test_is_holiday_normal_day_false(db):
    assert is_holiday(db, "2029-05-02") is False


def test_2027_public_holidays_seeded(db):
    rows = get_holidays(db, 2027)
    dates = {h["date"]: h["name"] for h in rows}
    assert dates["2027-01-01"] == "신정"
    assert dates["2027-02-07"] == "설날"
    assert dates["2027-02-09"] == "대체공휴일(설날)"
    assert dates["2027-08-16"] == "대체공휴일(광복절)"
    assert dates["2027-10-11"] == "대체공휴일(한글날)"
    assert dates["2027-12-27"] == "대체공휴일(크리스마스)"
    assert "2027-05-01" in dates  # 근로자의날 (합성)


def test_2026_holidays_include_constitution_day_and_labor_day(db):
    rows = get_holidays(db, 2026)
    dates = {h["date"]: h["name"] for h in rows}
    assert dates["2026-07-17"] == "제헌절"
    assert dates["2026-05-01"] == "노동절"


def test_2026_chuseok_dates(db):
    # 9/26 토요일 겹침. 설날, 추석은 일요일 겹침만 대체 대상
    rows = get_holidays(db, 2026)
    dates = {h["date"]: h["name"] for h in rows}
    assert dates["2026-09-24"] == "추석연휴"
    assert dates["2026-09-25"] == "추석"
    assert dates["2026-09-26"] == "추석연휴"
    assert "2026-09-27" not in dates
    assert "2026-09-28" not in dates


def test_2027_holidays_include_labor_day_substitute(db):
    rows = get_holidays(db, 2027)
    dates = {h["date"]: h["name"] for h in rows}
    assert dates["2027-05-01"] == "노동절"
    assert dates["2027-05-03"] == "대체공휴일(노동절)"
    assert dates["2027-07-17"] == "제헌절"
    assert dates["2027-07-19"] == "대체공휴일(제헌절)"


def test_calendar_uses_rest_off_day():
    sched = {"rest_day": 0, "off_day": 2}  # 월요일 주휴, 수요일 무급휴무
    cal = build_calendar_data([], "2026-09", schedule=sched)
    # 2026-09-07은 월요일
    day7 = next(d for d in cal["days"] if d["day"] == 7)
    assert day7["is_weekend"] is True
    day2 = next(d for d in cal["days"] if d["day"] == 2)  # 수요일
    assert day2["is_weekend"] is True
    day1 = next(d for d in cal["days"] if d["day"] == 1)  # 화요일
    assert day1["is_weekend"] is False


def test_calendar_default_sat_sun():
    cal = build_calendar_data([], "2026-09")
    day6 = next(d for d in cal["days"] if d["day"] == 6)  # 일요일
    assert day6["is_weekend"] is True
