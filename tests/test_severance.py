from core.pay_items import ensure_default_items, get_items
from core.severance import calc_severance


def _mk_emp(db, hire_date, resign_date=None, monthly_work_hours=0):
    cid = db.execute("INSERT INTO client_companies (name) VALUES ('퇴직금테스트')").lastrowid
    ensure_default_items(db, cid)
    items = {it["code"]: it["id"] for it in get_items(db, cid)}
    eid = db.execute(
        """INSERT INTO employees (name, company_id, hire_date, resign_date, monthly_work_hours, status)
           VALUES ('근로자', ?, ?, ?, ?, 'retired')""",
        (cid, hire_date, resign_date, monthly_work_hours),
    ).lastrowid
    db.commit()
    return cid, eid, items


def _mk_payslip(db, eid, year, month, items, amounts):
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


def test_window_boundaries(db):
    _, eid, _ = _mk_emp(db, "2020-01-01", resign_date="2026-09-15")
    basis = calc_severance(db, eid)
    assert basis["window_start"] == "2026-06-15"
    assert basis["window_end"] == "2026-09-14"
    assert basis["window_days"] == 92
    assert [w["window_days"] for w in basis["window"]] == [16, 31, 31, 14]
    assert [w["month_days"] for w in basis["window"]] == [30, 31, 31, 30]


def test_partial_month_proration(db):
    _, eid, items = _mk_emp(db, "2020-01-01", resign_date="2026-09-15", monthly_work_hours=300)
    _mk_payslip(db, eid, 2026, 6, items, {"BASE": 3_000_000})
    _mk_payslip(db, eid, 2026, 7, items, {"BASE": 3_000_000})
    _mk_payslip(db, eid, 2026, 8, items, {"BASE": 3_000_000})
    # 퇴사월(9월) 명세서는 아직 없음

    basis = calc_severance(db, eid)
    rows = {w["month"]: w for w in basis["window"]}
    assert rows[6]["prorated"] == 1_600_000  # 3,000,000 * 16/30
    assert rows[7]["prorated"] == 3_000_000
    assert rows[8]["prorated"] == 3_000_000
    assert rows[9]["prorated"] == 0
    assert rows[9]["has_payslip"] is False
    assert basis["window_wage"] == 7_600_000
    assert basis["window_days"] == 92


def test_bonus_annualized_3_12(db):
    _, eid, items = _mk_emp(db, "2020-01-01", resign_date="2026-09-15", monthly_work_hours=300)
    _mk_payslip(db, eid, 2026, 3, items, {"BASE": 3_000_000, "BONUS": 1_200_000})
    _mk_payslip(db, eid, 2026, 6, items, {"BASE": 3_000_000, "ANNUAL": 600_000})

    basis = calc_severance(db, eid)
    assert basis["bonus_total"] == 1_800_000
    assert basis["bonus_part"] == round(1_800_000 * 3 / 12)


def test_ordinary_wage_floor(db):
    # 평균임금 계산기간 임금은 적고, 최근 명세서 기준 통상임금이 더 큰 경우
    _, eid, items = _mk_emp(db, "2020-01-01", resign_date="2026-09-15", monthly_work_hours=0)
    _mk_payslip(db, eid, 2026, 6, items, {"BASE": 2_000_000})
    _mk_payslip(db, eid, 2026, 7, items, {"BASE": 2_000_000})
    _mk_payslip(db, eid, 2026, 8, items, {"BASE": 2_000_000})

    basis = calc_severance(db, eid)
    assert basis["used"] == "ordinary"
    assert basis["avg_salary"] == basis["ordinary_daily"]
    assert basis["ordinary_daily"] > basis["daily_avg"]


def test_under_one_year_ineligible(db):
    _, eid, _ = _mk_emp(db, "2026-01-01", resign_date="2026-09-15")
    basis = calc_severance(db, eid)
    assert basis["eligible"] is False
    assert basis["amount"] == 0
    assert "1년" in basis["reason"]


def test_short_hours_ineligible(db):
    _, eid, _ = _mk_emp(db, "2020-01-01", resign_date="2026-09-15", monthly_work_hours=40)
    basis = calc_severance(db, eid)
    assert basis["eligible"] is False
    assert "15시간" in basis["reason"]


def test_paid_record_untouched(db, seed, login):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (a,))
    db.commit()
    from core.pay_items import ensure_default_items as ensure_items
    ensure_items(db, a)
    items = {it["code"]: it["id"] for it in get_items(db, a)}
    eid = db.execute(
        """INSERT INTO employees (name, company_id, hire_date, resign_date, status)
           VALUES ('퇴사자', ?, '2020-01-01', '2026-09-15', 'retired')""",
        (a,),
    ).lastrowid
    _mk_payslip(db, eid, 2026, 6, items, {"BASE": 3_000_000})
    _mk_payslip(db, eid, 2026, 7, items, {"BASE": 3_000_000})
    _mk_payslip(db, eid, 2026, 8, items, {"BASE": 3_000_000})
    rec_id = db.execute(
        """INSERT INTO severance_records (employee_id, calc_date, avg_salary, tenure_days, amount, status)
           VALUES (?, '2026-09-15', 11111, 2449, 823456, 'paid')""",
        (eid,),
    ).lastrowid
    db.commit()

    c = login("t_staff")
    c.post("/hr-book", data={"book": a, "next": "/severance/estimate"})
    html = c.get(f"/severance/{eid}").text
    assert "823,456" in html

    # 급여 데이터가 바뀌어도 지급완료 건은 재계산 제외
    _mk_payslip(db, eid, 2026, 9, items, {"BASE": 99_999_999})
    c.get(f"/severance/{eid}")
    row = db.execute("SELECT avg_salary, amount FROM severance_records WHERE id=?", (rec_id,)).fetchone()
    assert row["avg_salary"] == 11111
    assert row["amount"] == 823456


def test_pending_record_recalculated_on_open(db, seed, login):
    a = seed["a"]["company"]
    db.execute("UPDATE client_companies SET payroll_delegated=1 WHERE id=?", (a,))
    db.commit()
    from core.pay_items import ensure_default_items as ensure_items
    ensure_items(db, a)
    items = {it["code"]: it["id"] for it in get_items(db, a)}
    eid = db.execute(
        """INSERT INTO employees (name, company_id, hire_date, resign_date, status)
           VALUES ('퇴사예정자', ?, '2020-01-01', '2026-09-15', 'retired')""",
        (a,),
    ).lastrowid
    _mk_payslip(db, eid, 2026, 6, items, {"BASE": 3_000_000})
    _mk_payslip(db, eid, 2026, 7, items, {"BASE": 3_000_000})
    _mk_payslip(db, eid, 2026, 8, items, {"BASE": 3_000_000})
    db.execute(
        """INSERT INTO severance_records (employee_id, calc_date, avg_salary, tenure_days, amount, status)
           VALUES (?, '2026-09-15', 0, 0, 0, 'pending')""",
        (eid,),
    )
    db.commit()

    c = login("t_staff")
    c.post("/hr-book", data={"book": a, "next": "/severance/estimate"})
    c.get(f"/severance/{eid}")
    row = db.execute("SELECT avg_salary, amount FROM severance_records WHERE employee_id=?", (eid,)).fetchone()
    assert row["avg_salary"] > 0
    assert row["amount"] > 0


def test_maternity_leave_excluded(db):
    _, eid, items = _mk_emp(db, "2020-01-01", resign_date="2026-09-15", monthly_work_hours=300)
    for m in (6, 7, 8):
        _mk_payslip(db, eid, 2026, m, items, {"BASE": 3_000_000})
    db.execute(
        """INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, status)
           VALUES (?, 'maternity', '2026-07-01', '2026-07-31', 31, 'approved')""",
        (eid,),
    )
    db.commit()

    basis = calc_severance(db, eid)
    rows = {w["month"]: w for w in basis["window"]}
    assert rows[7]["excluded_days"] == 31
    assert rows[7]["prorated"] == 0
    assert basis["excluded_days_total"] == 31
