import calendar
from datetime import date, timedelta

from core.payroll import STANDARD_MONTHLY_HOURS

# 근로기준법 시행령 제2조 제1항 평균임금 산정 제외 기간. 근태에 유형이 있는 건 출산전후휴가뿐이고
# 휴업/육아휴직/업무상 요양은 기록 부재. 화면에 수동 보정 안내만 표시
EXCLUDE_LEAVE = ("maternity",)
NOT_TRACKED_NOTE = "휴업, 육아휴직, 업무상 부상/질병 요양 기간은 자동 제외되지 않습니다. 해당 기간이 있다면 수동으로 보정하세요."

# 소득세법 48조 근속연수공제. (상한연수, 기준연수, 기준액, 연 공제액)
TENURE_DED_TABLE = (
    (5, 0, 0, 1_000_000),
    (10, 5, 5_000_000, 2_000_000),
    (20, 10, 15_000_000, 2_500_000),
    (None, 20, 40_000_000, 3_000_000),
)

# 환산급여공제. (상한액, 기준액, 공제액, 초과율%)
CONV_DED_TABLE = (
    (8_000_000, 0, 0, 100),
    (70_000_000, 8_000_000, 8_000_000, 60),
    (100_000_000, 70_000_000, 45_200_000, 55),
    (300_000_000, 100_000_000, 61_700_000, 45),
    (None, 300_000_000, 151_700_000, 35),
)

# 소득세법 55조 기본세율. (상한액, 기준액, 세액, 초과율%)
TAX_TABLE = (
    (14_000_000, 0, 0, 6),
    (50_000_000, 14_000_000, 840_000, 15),
    (88_000_000, 50_000_000, 6_240_000, 24),
    (150_000_000, 88_000_000, 15_360_000, 35),
    (300_000_000, 150_000_000, 37_060_000, 38),
    (500_000_000, 300_000_000, 94_060_000, 40),
    (1_000_000_000, 500_000_000, 174_060_000, 42),
    (None, 1_000_000_000, 384_060_000, 45),
)


def _progressive(value, table):
    for upper, threshold, base, rate in table:
        if upper is None or value <= upper:
            return base + (value - threshold) * rate // 100


def calc_sev_tax(amount, hire_date, resign_date):
    hire_dt = date.fromisoformat(hire_date)
    resign_dt = date.fromisoformat(resign_date)
    # 1년 미만 끝수는 1년으로 계산
    md, hd = (resign_dt.month, resign_dt.day), (hire_dt.month, hire_dt.day)
    years = resign_dt.year - hire_dt.year - (md < hd)
    years = max(1, years + (md != hd))

    for upper, start, base, per in TENURE_DED_TABLE:
        if upper is None or years <= upper:
            years_ded = min(amount, base + (years - start) * per)
            break
    converted = (amount - years_ded) * 12 // years
    conv_ded = _progressive(converted, CONV_DED_TABLE)
    base = max(0, converted - conv_ded)
    conv_tax = _progressive(base, TAX_TABLE)
    income_tax = conv_tax * years // 12 // 10 * 10
    local_tax = income_tax // 100 * 10
    net = amount - income_tax - local_tax

    return {
        "years": years, "years_ded": years_ded, "converted": converted, "conv_ded": conv_ded,
        "base": base, "conv_tax": conv_tax, "income_tax": income_tax, "local_tax": local_tax, "net": net,
    }


def calc_ordinary_daily(conn, emp_id, resign_date):
    emp = conn.execute("SELECT monthly_work_hours FROM employees WHERE id=?", (emp_id,)).fetchone()
    monthly_hours = emp["monthly_work_hours"] if emp else 0
    resign_dt = date.fromisoformat(resign_date)
    latest_slip = conn.execute(
        """SELECT id FROM payslips
           WHERE employee_id=? AND (pay_year * 100 + pay_month) <= ?
           ORDER BY pay_year DESC, pay_month DESC LIMIT 1""",
        (emp_id, resign_dt.year * 100 + resign_dt.month),
    ).fetchone()
    ordinary_sum = 0
    if latest_slip:
        ordinary_sum = conn.execute(
            """SELECT COALESCE(SUM(pi.amount),0) FROM payslip_items pi
               JOIN pay_items it ON it.id=pi.item_id
               WHERE pi.payslip_id=? AND it.ordinary=1""",
            (latest_slip["id"],),
        ).fetchone()[0]
    denom = monthly_hours or STANDARD_MONTHLY_HOURS
    return round(ordinary_sum / denom * 8) if denom else 0


def _sub_months(d, n):
    total = d.year * 12 + (d.month - 1) - n
    y, m = divmod(total, 12)
    m += 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _months_between(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            m = 1
            y += 1


def _excluded_periods(conn, emp_id, start, end):
    placeholders = ",".join("?" * len(EXCLUDE_LEAVE))
    rows = conn.execute(
        f"""SELECT start_date, end_date FROM leave_requests
            WHERE employee_id=? AND status='approved' AND leave_type IN ({placeholders})
            AND start_date <= ? AND end_date >= ?""",
        (emp_id, *EXCLUDE_LEAVE, end.isoformat(), start.isoformat()),
    ).fetchall()
    periods = []
    for r in rows:
        s = max(start, date.fromisoformat(r["start_date"]))
        e = min(end, date.fromisoformat(r["end_date"]))
        if s <= e:
            periods.append((s, e))
    return periods


def _overlap_days(periods, seg_start, seg_end):
    days = 0
    for s, e in periods:
        ov_s, ov_e = max(s, seg_start), min(e, seg_end)
        if ov_s <= ov_e:
            days += (ov_e - ov_s).days + 1
    return days


def _payslip_id(conn, emp_id, year, month):
    row = conn.execute(
        "SELECT id FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
        (emp_id, year, month),
    ).fetchone()
    return row["id"] if row else None


def calc_severance(conn, emp_id, resign_date=None):
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        return None

    rd = resign_date or emp["resign_date"]
    hd = emp["hire_date"]
    if not rd or not hd:
        return None

    resign_dt = date.fromisoformat(rd)
    hire_dt = date.fromisoformat(hd)
    tenure_days = (resign_dt - hire_dt).days
    monthly_hours = emp["monthly_work_hours"] or 0

    reasons = []
    if tenure_days < 365:
        reasons.append("근속기간 1년 미만")
    if monthly_hours and monthly_hours < 60:
        reasons.append("4주 평균 주 15시간 미만")

    if reasons:
        return {
            "eligible": False,
            "reason": ", ".join(reasons),
            "tenure_days": tenure_days,
            "avg_salary": 0,
            "amount": 0,
        }

    window_end = resign_dt - timedelta(days=1)
    window_start = _sub_months(resign_dt, 3)
    bonus_start = _sub_months(resign_dt, 12)

    excluded = _excluded_periods(conn, emp_id, window_start, window_end)

    window_rows = []
    window_days = 0
    window_wage = 0.0
    for y, m in _months_between(window_start, window_end):
        month_days = calendar.monthrange(y, m)[1]
        month_first = date(y, m, 1)
        month_last = date(y, m, month_days)
        seg_start = max(window_start, month_first)
        seg_end = min(window_end, month_last)
        raw_days = (seg_end - seg_start).days + 1
        ex_days = _overlap_days(excluded, seg_start, seg_end)
        effective_days = max(0, raw_days - ex_days)

        slip_id = _payslip_id(conn, emp_id, y, m)
        wage = 0
        if slip_id:
            wage = conn.execute(
                """SELECT COALESCE(SUM(pi.amount),0) FROM payslip_items pi
                   JOIN pay_items it ON it.id=pi.item_id
                   WHERE pi.payslip_id=? AND it.avg_wage=1 AND it.bonus=0""",
                (slip_id,),
            ).fetchone()[0]
        prorated = wage * effective_days / month_days if month_days else 0

        window_rows.append({
            "year": y,
            "month": m,
            "period": f"{seg_start.isoformat()} ~ {seg_end.isoformat()}",
            "month_days": month_days,
            "window_days": raw_days,
            "excluded_days": ex_days,
            "effective_days": effective_days,
            "wage": wage,
            "prorated": round(prorated),
            "has_payslip": slip_id is not None,
        })
        window_days += effective_days
        window_wage += prorated

    bonus_total = 0
    for y, m in _months_between(bonus_start, window_end):
        slip_id = _payslip_id(conn, emp_id, y, m)
        if not slip_id:
            continue
        bonus_total += conn.execute(
            """SELECT COALESCE(SUM(pi.amount),0) FROM payslip_items pi
               JOIN pay_items it ON it.id=pi.item_id
               WHERE pi.payslip_id=? AND it.bonus=1""",
            (slip_id,),
        ).fetchone()[0]
    bonus_part = bonus_total * 3 / 12

    daily_avg = (window_wage + bonus_part) / window_days if window_days else 0
    ordinary_daily = calc_ordinary_daily(conn, emp_id, resign_dt.isoformat())

    used = "avg_wage" if daily_avg >= ordinary_daily else "ordinary"
    avg_salary = round(max(daily_avg, ordinary_daily))
    amount = round(avg_salary * 30 * tenure_days / 365)

    return {
        "eligible": True,
        "reason": "",
        "tenure_days": tenure_days,
        "resign_date": resign_dt.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window": window_rows,
        "window_days": window_days,
        "window_wage": round(window_wage),
        "bonus_total": bonus_total,
        "bonus_part": round(bonus_part),
        "daily_avg": round(daily_avg),
        "ordinary_daily": round(ordinary_daily),
        "used": used,
        "avg_salary": avg_salary,
        "amount": amount,
        "exclude_note": NOT_TRACKED_NOTE,
        "excluded_days_total": sum(r["excluded_days"] for r in window_rows),
    }
