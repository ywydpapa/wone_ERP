
NATIONAL_PENSION_RATE = 0.045
HEALTH_INSURANCE_RATE = 0.03545
LONG_CARE_RATE = 0.1281
EMPLOYMENT_INSURANCE_RATE = 0.009

NATIONAL_PENSION_UPPER = 5900000
NATIONAL_PENSION_LOWER = 370000


def calc_national_pension(gross):
    base = max(NATIONAL_PENSION_LOWER, min(gross, NATIONAL_PENSION_UPPER))
    return round(base * NATIONAL_PENSION_RATE / 10) * 10


def calc_health_insurance(gross):
    health = round(gross * HEALTH_INSURANCE_RATE / 10) * 10
    long_care = round(health * LONG_CARE_RATE / 10) * 10
    return health + long_care


def calc_employment_insurance(gross):
    return round(gross * EMPLOYMENT_INSURANCE_RATE / 10) * 10


def calc_income_tax(gross):
    # 간이세액표 근사치
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
    return round(monthly / 10) * 10


def calc_resident_tax(income_tax):
    return round(income_tax * 0.1 / 10) * 10


def calc_deductions(gross):
    national_pension = calc_national_pension(gross)
    health_insurance = calc_health_insurance(gross)
    employment_insurance = calc_employment_insurance(gross)
    income_tax = calc_income_tax(gross)
    resident_tax = calc_resident_tax(income_tax)
    total = national_pension + health_insurance + employment_insurance + income_tax + resident_tax
    return {
        "national_pension": national_pension,
        "health_insurance": health_insurance,
        "employment_insurance": employment_insurance,
        "income_tax": income_tax,
        "resident_tax": resident_tax,
        "total_deduction": total,
    }


def build_payslip(base_salary, overtime_pay=0, disability_allowance=0, meal_allowance=0):
    gross = base_salary + overtime_pay + disability_allowance + meal_allowance
    deductions = calc_deductions(gross)
    return {
        "base_salary": base_salary,
        "overtime_pay": overtime_pay,
        "disability_allowance": disability_allowance,
        "meal_allowance": meal_allowance,
        "gross_pay": gross,
        **deductions,
        "net_pay": gross - deductions["total_deduction"],
    }
