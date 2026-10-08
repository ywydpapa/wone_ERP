from core.payroll import build_payslip, calc_ordinary_hourly, calc_premium_pay
from core.attendance import get_month_work_stats


def test_taxable_with_meal_over_limit():
    items = [
        {"amount": 3_000_000, "taxable": 1, "tax_free_limit": 0},
        {"amount": 300_000, "taxable": 1, "tax_free_limit": 200_000},
    ]
    ps = build_payslip(items, {}, 1)
    assert ps["gross_pay"] == 3_300_000
    # 식대 비과세 한도(20만원) 초과분만 과세표준에 포함
    assert ps["taxable"] == 3_000_000 + 100_000
    assert ps["tax_free_total"] == 200_000


def test_calc_ordinary_hourly():
    assert calc_ordinary_hourly(2_090_000, 209) == 10_000
    assert calc_ordinary_hourly(2_090_000, 0) == 0


def test_five_plus_overtime_1_5x():
    r = calc_premium_pay(hourly=10_000, ot_mins=60, night_mins=0, holiday_day_mins=[], five_plus=True)
    assert r["OT"] == 15_000


def test_five_plus_night_additive_0_5x():
    r = calc_premium_pay(hourly=10_000, ot_mins=0, night_mins=60, holiday_day_mins=[], five_plus=True)
    # 야간은 기본급/연장수당에 이미 포함된 근로시간 위에 0.5배만 가산
    assert r["NIGHT"] == 5_000


def test_five_plus_holiday_9h_split():
    r = calc_premium_pay(hourly=10_000, ot_mins=0, night_mins=0, holiday_day_mins=[540], five_plus=True)
    assert r["HOLIDAY"] == int(8 * 10_000 * 1.5 + 1 * 10_000 * 2.0)


def test_under_five_no_premium():
    r = calc_premium_pay(hourly=10_000, ot_mins=60, night_mins=60, holiday_day_mins=[540], five_plus=False)
    assert r["OT"] == 10_000
    assert r["NIGHT"] == 0
    assert r["HOLIDAY"] == 90_000  # 9시간 전부 1.0배, 8시간 분할 없음


def test_month_work_stats_holiday_day_mins(db):
    cid = db.execute("INSERT INTO client_companies (name) VALUES ('프리미엄테스트')").lastrowid
    eid = db.execute(
        "INSERT INTO employees (name, company_id, status) VALUES ('근로자', ?, 'active')", (cid,)
    ).lastrowid
    # 2026-09-06(일)=주휴일 9시간 근무
    db.execute(
        "INSERT INTO attendance (employee_id, work_date, clock_in, clock_out, work_minutes, status) "
        "VALUES (?, '2026-09-06', '09:00', '19:00', 540, 'normal')", (eid,)
    )
    db.commit()

    stats = get_month_work_stats(db, eid, "2026-09")
    assert stats["holiday_day_mins"] == [540]
