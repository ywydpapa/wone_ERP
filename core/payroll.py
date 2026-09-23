
MEAL_TAX_FREE_LIMIT = 200000

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


def calc_income_tax(gross, dependents=1):
    # 간이세액표 근사치. 부양가족 1인당 월 12,500원 추가 공제
    annual = gross * 12
    if annual <= 14_000_000:
        tax = 0
    elif annual <= 50_000_000:
        tax = (annual - 14_000_000) * 0.06
    elif annual <= 88_000_000:
        tax = 2_160_000 + (annual - 50_000_000) * 0.15
    elif annual <= 150_000_000:
        tax = 7_860_000 + (annual - 88_000_000) * 0.24
    elif annual <= 300_000_000:
        tax = 22_740_000 + (annual - 150_000_000) * 0.35
    else:
        tax = 75_240_000 + (annual - 300_000_000) * 0.38
    monthly = tax / 12
    deduction = 12500 * max(1, int(dependents))
    monthly = max(0, monthly - deduction)
    return round(monthly / 10) * 10


def calc_deductions(taxable, rates, dependents=1):
    national_pension = calc_national_pension(taxable, rates)
    health, long_care = calc_health_insurance(taxable, rates)
    employment_insurance = round(taxable * rates.get("employment_insurance", 0.009) / 10) * 10
    income_tax = calc_income_tax(taxable, dependents)
    resident_tax = round(income_tax * 0.1 / 10) * 10
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


def build_payslip(base_salary, overtime_pay, disability_allowance, meal_allowance, rates, dependents=1):
    gross = base_salary + overtime_pay + disability_allowance + meal_allowance
    tax_free_meal = min(meal_allowance, MEAL_TAX_FREE_LIMIT)
    taxable = gross - tax_free_meal
    deductions = calc_deductions(taxable, rates, dependents)
    return {
        "base_salary": base_salary,
        "overtime_pay": overtime_pay,
        "disability_allowance": disability_allowance,
        "meal_allowance": meal_allowance,
        "gross_pay": gross,
        "tax_free_meal": tax_free_meal,
        "taxable": taxable,
        **deductions,
        "net_pay": gross - deductions["total_deduction"],
    }


EMPLOYER_ACCIDENT_RATE = 0.007  # 기본 업종 산재보험료율


def calc_employer_insurance(gross, rates):
    pension_rate = rates.get("national_pension", 0.0475)
    health_rate = rates.get("health_insurance", 0.03595)
    long_care_rate = rates.get("long_care", 0.1314)
    ei_rate = 0.009  # 150인 미만 사업장

    pension = round(gross * pension_rate / 10) * 10
    health = round(gross * health_rate / 10) * 10
    # 장기요양은 건강보험액 기준 계산
    long_care = round(health * long_care_rate / 10) * 10
    employment = round(gross * ei_rate / 10) * 10
    accident = round(gross * EMPLOYER_ACCIDENT_RATE / 10) * 10
    return {
        "employer_pension": pension,
        "employer_health": health + long_care,
        "employer_employment": employment,
        "employer_accident": accident,
    }


def calc_overtime_pay(base_salary, monthly_work_hours, overtime_minutes):
    if not monthly_work_hours:
        return 0
    hourly = base_salary / monthly_work_hours
    ot_hours = overtime_minutes / 60
    return int(hourly * 1.5 * ot_hours)
