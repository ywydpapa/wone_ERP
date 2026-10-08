import bisect
import csv
import os

from core.attendance import get_month_work_stats

STANDARD_MONTHLY_HOURS = 209  # 주 40시간 + 주휴 8시간 기준 월 소정근로시간

INSURANCE_LABELS = {
    "national_pension": "국민연금",
    "health_insurance": "건강보험",
    "long_care": "장기요양보험",
    "employment_insurance": "고용보험",
    "pension_upper": "국민연금 상한액",
    "pension_lower": "국민연금 하한액",
}


def get_rates(conn, pay_year, pay_month):
    effective = f"{pay_year}-{pay_month:02d}-01"
    rows = conn.execute("""
        SELECT r.rate_key, r.rate_value FROM insurance_rates r
        INNER JOIN (
            SELECT rate_key, MAX(effective_date) AS max_date
            FROM insurance_rates WHERE effective_date <= ?
            GROUP BY rate_key
        ) latest ON r.rate_key = latest.rate_key AND r.effective_date = latest.max_date
    """, (effective,)).fetchall()
    return {r["rate_key"]: r["rate_value"] for r in rows}


def calc_national_pension(gross, rates):
    upper = int(rates.get("pension_upper", 5900000))
    lower = int(rates.get("pension_lower", 370000))
    rate = rates.get("national_pension", 0.0475)
    base = max(lower, min(gross, upper))
    return round(base * rate / 10) * 10


def calc_health_insurance(gross, rates):
    health = round(gross * rates.get("health_insurance", 0.03595) / 10) * 10
    long_care = round(health * rates.get("long_care", 0.1314) / 10) * 10
    return health, long_care


# 근로소득 간이세액표 (소득세법 시행령 별표2, 2026.2.27 개정). 월급여 이상/미만, 공제대상가족 1~11명
with open(os.path.join(os.path.dirname(__file__), "simple_tax.csv"), encoding="utf-8") as f:
    TAX_TABLE = [tuple(int(v) for v in row) for row in list(csv.reader(f))[1:]]
TAX_LOS = [r[0] for r in TAX_TABLE]

# 월급여 10,000천원 세액. 초과 구간은 이 값에 가산
TAX_10M = (1507400, 1431570, 1200840, 1170840, 1140840, 1110840, 1080840, 1050840, 1020840, 990840, 960840)

# (상한, 초과 기준액, 가산액, 적용률 1/10000). 3천만원 이하 구간은 98% 반영한 율
TAX_OVER_10M = [
    (14_000_000, 10_000_000, 25_000, 3430),
    (28_000_000, 14_000_000, 1_397_000, 3724),
    (30_000_000, 28_000_000, 6_610_600, 3920),
    (45_000_000, 30_000_000, 7_394_600, 4000),
    (87_000_000, 45_000_000, 13_394_600, 4200),
    (None, 87_000_000, 31_034_600, 4500),
]


def _table_tax(gross, fam):
    if gross < 10_000_000:
        return TAX_TABLE[bisect.bisect_right(TAX_LOS, gross) - 1][fam + 1]
    tax = TAX_10M[fam - 1]
    if gross == 10_000_000:
        return tax
    for upper, base, add, rate in TAX_OVER_10M:
        if upper is None or gross <= upper:
            return tax + add + (gross - base) * rate // 10000


def calc_income_tax(gross, dependents=1, children=0, rate=100):
    if gross < 770_000:
        return 0
    fam = max(1, dependents)
    if fam <= 11:
        tax = _table_tax(gross, fam)
    else:
        # 11명 초과분은 10명과 11명 세액 차이만큼 1명당 추가 차감
        t10, t11 = _table_tax(gross, 10), _table_tax(gross, 11)
        tax = max(0, t11 - (t10 - t11) * (fam - 11))
    # 8세 이상 20세 이하 자녀 공제
    if children == 1:
        tax -= 20_830
    elif children >= 2:
        tax -= 45_830 + (children - 2) * 33_330
    # 원천징수비율 80/100/120% (시행령 194조), 10원 미만 절사
    return max(0, tax) * rate // 100 // 10 * 10


def calc_deductions(taxable, rates, dependents=1, children=0, rate=100):
    national_pension = calc_national_pension(taxable, rates)
    health, long_care = calc_health_insurance(taxable, rates)
    employment_insurance = round(taxable * rates.get("employment_insurance", 0.009) / 10) * 10
    income_tax = calc_income_tax(taxable, dependents, children, rate)
    resident_tax = income_tax // 100 * 10
    total = national_pension + health + long_care + employment_insurance + income_tax + resident_tax
    return {
        "national_pension": national_pension,
        "health_insurance": health,
        "long_care": long_care,
        "employment_insurance": employment_insurance,
        "income_tax": income_tax,
        "resident_tax": resident_tax,
        "total_deduction": total,
    }


def build_payslip(items, rates, dependents=1, children=0, rate=100):
    gross = sum(it["amount"] for it in items)
    taxable = 0
    for it in items:
        if it.get("tax_free_limit"):
            taxable += max(0, it["amount"] - it["tax_free_limit"])
        elif it.get("taxable"):
            taxable += it["amount"]
    tax_free_total = gross - taxable
    deductions = calc_deductions(taxable, rates, dependents, children, rate)
    return {
        "items": items,
        "gross_pay": gross,
        "tax_free_total": tax_free_total,
        "taxable": taxable,
        **deductions,
        "net_pay": gross - deductions["total_deduction"],
    }


EMPLOYER_ACCIDENT_RATE = 0.007  # 기본 업종 산재보험료율
EMPLOYER_EMPLOYMENT_RATE = 0.0115  # 고용보험 0.9% + 고용안정 직업능력개발 0.25% (150인 미만 우선지원대상기업)


def calc_employer_insurance(payslip):
    taxable = payslip["taxable"]
    employment = round(taxable * EMPLOYER_EMPLOYMENT_RATE / 10) * 10
    accident = round(taxable * EMPLOYER_ACCIDENT_RATE / 10) * 10
    return {
        # 국민연금, 건강보험(+장기요양)은 근로자 부담분과 동일 (동일 보수월액, 동일 요율)
        "employer_pension": payslip["national_pension"],
        "employer_health": payslip["health_insurance"] + payslip["long_care"],
        "employer_employment": employment,
        "employer_accident": accident,
    }


def is_five_plus(conn, company_id):
    # 원 내부(book 0)는 client_companies 행이 없음. 소속 재직자 수 기준
    if company_id == 0:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM employees WHERE company_id IS NULL AND status='active'"
        ).fetchone()[0]
        return cnt >= 5
    row = conn.execute(
        "SELECT employee_count FROM client_companies WHERE id=?", (company_id,)
    ).fetchone()
    return bool(row and (row["employee_count"] or 0) >= 5)


def calc_ordinary_hourly(ordinary_total, monthly_hours):
    if not monthly_hours:
        return 0
    return ordinary_total / monthly_hours


def calc_premium_pay(hourly, ot_mins, night_mins, holiday_day_mins, five_plus):
    # 근로기준법 제56조 가산수당. 5인 미만은 가산 없음(시행령 별표1): 연장/휴일은 1.0, 야간은 이미 근무시간에 포함된 값. 가산 0
    ot_hours = ot_mins / 60
    night_hours = night_mins / 60
    ot_mult = 1.5 if five_plus else 1.0
    night_mult = 0.5 if five_plus else 0
    ot_amount = int(hourly * ot_mult * ot_hours)
    night_amount = int(hourly * night_mult * night_hours)

    holiday_amount = 0.0
    holiday_hours = 0.0
    for mins in holiday_day_mins:
        hours = mins / 60
        holiday_hours += hours
        if five_plus:
            normal_h = min(hours, 8)
            over_h = max(0, hours - 8)
            holiday_amount += hourly * 1.5 * normal_h + hourly * 2.0 * over_h
        else:
            holiday_amount += hourly * hours

    return {
        "OT": ot_amount,
        "NIGHT": night_amount,
        "HOLIDAY": int(holiday_amount),
        "ot_hours": ot_hours,
        "night_hours": night_hours,
        "holiday_hours": holiday_hours,
    }


def _item_calc_note(code, tax_free_limit, hourly, hours, five_plus, overridden):
    if code == "BASE":
        note = "기본급 월정액"
    elif code == "OT":
        mult = 1.5 if five_plus else 1.0
        note = f"연장 {round(hours.get('ot', 0), 1):g}h × {int(hourly):,} × {mult:g}" if hourly else "-"
    elif code == "NIGHT":
        note = f"야간 {round(hours.get('night', 0), 1):g}h × {int(hourly):,} × 0.5 (가산)" if hourly and five_plus else "-"
    elif code == "HOLIDAY":
        h = round(hours.get("holiday", 0), 1)
        note = f"휴일 {h:g}h (8h 이내 1.5배, 초과분 2배)" if five_plus else f"휴일 {h:g}h × 1.0 (5인 미만)"
    elif code == "DISABLE":
        note = "장애인 근로지원금 월정액"
    elif code == "MEAL":
        note = f"식대 월정액 (비과세 {tax_free_limit:,}원 한도)" if tax_free_limit else "식대 월정액"
    elif code == "BONUS":
        note = "상여금 입력값"
    elif code == "ANNUAL":
        note = "연차수당 입력값"
    else:
        note = "입력값"
    if overridden and code in ("OT", "NIGHT", "HOLIDAY"):
        note += " (수동 조정됨)"
    return note


def build_deduction_notes(payslip, rates, taxable):
    upper = int(rates.get("pension_upper", 5900000))
    lower = int(rates.get("pension_lower", 370000))
    pension_base = max(lower, min(taxable, upper))
    pension_rate = rates.get("national_pension", 0.0475)
    health_rate = rates.get("health_insurance", 0.03595)
    long_care_rate = rates.get("long_care", 0.1314)
    ei_rate = rates.get("employment_insurance", 0.009)

    return {
        "national_pension": f"국민연금 과세표준 {pension_base:,} × {pension_rate * 100:g}%",
        "health_insurance": f"건강보험 과세표준 {taxable:,} × {health_rate * 100:g}%",
        "long_care": f"장기요양보험 건강보험료 {payslip.get('health_insurance') or 0:,} × {long_care_rate * 100:g}%",
        "employment_insurance": f"고용보험 과세표준 {taxable:,} × {ei_rate * 100:g}%",
        "income_tax": "소득세 간이세액표 적용 (부양가족수, 자녀공제, 원천징수비율 반영)",
        "resident_tax": "주민세 소득세 × 10%",
    }


def build_payslip_detail(conn, emp_id, monthly_work_hours, payslip):
    year_month = f"{payslip['pay_year']}-{payslip['pay_month']:02d}"
    stats = get_month_work_stats(conn, emp_id, year_month)
    rates = get_rates(conn, payslip["pay_year"], payslip["pay_month"])
    five_plus = payslip.get("premium_rule") == "5인이상"

    rows = conn.execute(
        """SELECT pi.amount, pi.overridden, it.code, it.name, it.taxable, it.tax_free_limit, it.ordinary
           FROM payslip_items pi JOIN pay_items it ON it.id = pi.item_id
           WHERE pi.payslip_id=? ORDER BY it.sort, it.id""",
        (payslip["id"],),
    ).fetchall()

    ordinary_total = sum(r["amount"] for r in rows if r["ordinary"])
    hourly = calc_ordinary_hourly(ordinary_total, monthly_work_hours)

    ot_hours = stats["ot_mins"] / 60
    night_hours = stats["night_mins"] / 60
    holiday_hours = stats["holiday_mins"] / 60
    hours = {"ot": ot_hours, "night": night_hours, "holiday": holiday_hours}

    taxable = 0
    items = []
    for r in rows:
        if r["tax_free_limit"]:
            taxable += max(0, r["amount"] - r["tax_free_limit"])
        elif r["taxable"]:
            taxable += r["amount"]
        note = _item_calc_note(r["code"], r["tax_free_limit"], hourly, hours, five_plus, r["overridden"])
        items.append({
            "code": r["code"], "name": r["name"], "amount": r["amount"],
            "overridden": bool(r["overridden"]), "calc_note": note,
        })

    calc_notes = build_deduction_notes(payslip, rates, taxable)

    stats["work_hours"] = f"{round(stats['total_mins'] / 60, 1):g}"
    stats["ot_hours"] = f"{round(ot_hours, 1):g}"
    stats["night_hours"] = f"{round(night_hours, 1):g}"
    stats["holiday_hours"] = f"{round(holiday_hours, 1):g}"

    return stats, calc_notes, items
