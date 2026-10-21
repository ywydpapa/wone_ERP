from datetime import date

from tests.conftest import csrf
from core.pay_items import ensure_default_items, get_items
from core.leave_accrual import ensure_accrual
from core.severance import calc_sev_tax, calc_ordinary_daily


def _emp(db, book, name="홍길동", hire_date="2020-01-01", monthly_hours=209):
    return db.execute(
        "INSERT INTO employees (name, company_id, hire_date, status, monthly_work_hours) "
        "VALUES (?,?,?,'active',?)",
        (name, book, hire_date, monthly_hours),
    ).lastrowid


def _confirmed_payslip(db, eid, items, year, month, amounts):
    gross = sum(amounts.values())
    ps_id = db.execute(
        """INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, total_deduction, net_pay, status)
           VALUES (?,?,?,?,0,?,'confirmed')""",
        (eid, year, month, gross, gross),
    ).lastrowid
    for code, amount in amounts.items():
        db.execute(
            "INSERT INTO payslip_items (payslip_id, item_id, amount) VALUES (?,?,?)",
            (ps_id, items[code], amount),
        )
    db.commit()
    return ps_id


# 근속연수 끝수 올림

def test_tenure_years_round_up_on_remainder():
    assert calc_sev_tax(10_000_000, "2018-01-01", "2024-01-02")["years"] == 7
    assert calc_sev_tax(10_000_000, "2018-01-01", "2024-01-01")["years"] == 6


def test_tenure_years_minimum_one():
    assert calc_sev_tax(10_000_000, "2024-01-01", "2024-12-30")["years"] == 1


# 퇴직소득세 산출

def test_sev_tax_under_8m_converted_no_tax():
    r = calc_sev_tax(10_000_000, "2017-01-01", "2024-01-01")
    assert r["years"] == 7
    assert r["converted"] == 1_714_285
    assert r["income_tax"] == 0
    assert r["local_tax"] == 0
    assert r["net"] == 10_000_000


def test_sev_tax_hand_calc_5000만_5년():
    r = calc_sev_tax(50_000_000, "2019-01-01", "2024-01-01")
    assert r["years"] == 5
    assert r["years_ded"] == 5_000_000
    assert r["converted"] == 108_000_000
    assert r["conv_ded"] == 65_300_000
    assert r["base"] == 42_700_000
    assert r["conv_tax"] == 5_145_000
    assert r["income_tax"] == 2_143_750
    assert r["local_tax"] == 214_370
    assert r["net"] == 50_000_000 - 2_143_750 - 214_370


def test_sev_tax_truncate_10won():
    r = calc_sev_tax(20_000_000, "2016-01-01", "2023-01-01")
    assert r["income_tax"] == 151_990
    assert r["local_tax"] == 15_190


# 퇴사 처리 연동

def test_resign_saves_tax_and_leave_pay(db, seed, login):
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (seed["a"]["company"],))
    db.commit()
    a = seed["a"]["company"]
    ensure_default_items(db, a)
    items = {it["code"]: it["id"] for it in get_items(db, a)}
    eid = _emp(db, a, hire_date="2019-01-01")
    _confirmed_payslip(db, eid, items, 2026, 9, {"BASE": 3_000_000})
    ensure_accrual(db, eid, 2026)
    db.execute(
        "UPDATE leave_accruals SET granted=10, used=4 WHERE employee_id=? AND accrual_year=2026",
        (eid,),
    )
    db.commit()

    c = login("t_staff")
    tok = csrf(c, f"/hr/employees/{eid}/resign")
    r = c.post(
        f"/hr/employees/{eid}/resign",
        data={"csrf_token": tok, "resign_date": "2026-09-15", "resign_reason": "개인사정"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    rec = db.execute(
        "SELECT * FROM severance_records WHERE employee_id=? ORDER BY id DESC LIMIT 1", (eid,)
    ).fetchone()
    assert rec["leave_days"] == 6
    daily = calc_ordinary_daily(db, eid, "2026-09-15")
    assert rec["leave_pay"] == round(6 * daily)
    assert rec["net_amount"] == rec["amount"] - rec["income_tax"] - rec["local_tax"]


# 퇴사월 급여 목록 포함 여부

def test_payroll_list_includes_resign_month_excludes_next(db, seed, login):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (a,))
    eid = _emp(db, a, hire_date="2020-01-01")
    db.execute(
        "UPDATE employees SET status='retired', resign_date='2026-09-15' WHERE id=?", (eid,)
    )
    db.commit()

    c = login("a_mgr")
    html_sep = c.get("/payroll?year=2026&month=9").text
    assert "홍길동" in html_sep
    html_oct = c.get("/payroll?year=2026&month=10").text
    assert "홍길동" not in html_oct


# 퇴사월 급여 입력화면 ANNUAL 추천값

def test_payroll_edit_shows_unused_leave_suggestion(db, seed, login):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (a,))
    ensure_default_items(db, a)
    eid = _emp(db, a, hire_date="2020-01-01")
    db.execute(
        "UPDATE employees SET status='retired', resign_date='2026-09-15' WHERE id=?", (eid,)
    )
    ensure_accrual(db, eid, 2026)
    db.execute(
        "UPDATE leave_accruals SET granted=15, used=10 WHERE employee_id=? AND accrual_year=2026",
        (eid,),
    )
    db.commit()

    c = login("a_mgr")
    html = c.get(f"/payroll/{eid}?year=2026&month=9").text
    assert "미사용 연차 5일" in html


# 연차 잔여 단일화

def test_mypage_leave_matches_accrual_and_decreases_after_approval(db, seed, login):
    wk_user = seed["a"]["wk"]
    emp = db.execute("SELECT id FROM employees WHERE user_id=?", (wk_user,)).fetchone()
    eid = emp["id"]
    year = date.today().year
    ensure_accrual(db, eid, year)
    db.execute(
        "UPDATE leave_accruals SET granted=15, used=3 WHERE employee_id=? AND accrual_year=?",
        (eid, year),
    )
    db.commit()

    c = login("a_wk")
    html = c.get("/mypage/leave").text
    assert ">12.0<" in html

    today = date.today().isoformat()
    c.post("/mypage/leave", data={"leave_type": "annual", "start_date": today, "end_date": today, "days": "1", "reason": "개인"})
    lid = db.execute("SELECT id FROM leave_requests WHERE employee_id=?", (eid,)).fetchone()[0]

    m = login("a_mgr")
    tok = csrf(m, f"/client/leave/{lid}")
    m.post(f"/client/leave/{lid}/approve", data={"csrf_token": tok})

    bal_row = db.execute(
        "SELECT used FROM leave_accruals WHERE employee_id=? AND accrual_year=?", (eid, year)
    ).fetchone()
    assert bal_row["used"] == 4

    html2 = c.get("/mypage/leave").text
    assert ">11.0<" in html2
