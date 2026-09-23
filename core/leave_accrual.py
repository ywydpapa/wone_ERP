from datetime import date


def calc_annual_leave(hire_date, ref_date):
    if isinstance(hire_date, str):
        hire_date = date.fromisoformat(hire_date)
    if isinstance(ref_date, str):
        ref_date = date.fromisoformat(ref_date)

    years = (ref_date - hire_date).days / 365.25

    if years < 1:
        # 1년 미만: 입사일 기준 매달 1일 (최대 11일)
        months = 0
        d = hire_date
        while True:
            m = d.month + 1
            y = d.year + (1 if m > 12 else 0)
            m = m if m <= 12 else m - 12
            try:
                nxt = d.replace(year=y, month=m)
            except ValueError:
                import calendar
                last = calendar.monthrange(y, m)[1]
                nxt = d.replace(year=y, month=m, day=last)
            if nxt > ref_date:
                break
            months += 1
            d = nxt
        return min(months, 11)

    # 1년 이상 기본 15일
    base = 15
    # 3년 이상부터 2년마다 +1 (최대 25일)
    if years >= 3:
        extra = int((years - 1) / 2)
        base = min(15 + extra, 25)

    return base


def ensure_accrual(conn, emp_id, year):
    row = conn.execute(
        "SELECT * FROM leave_accruals WHERE employee_id=? AND accrual_year=?",
        (emp_id, year),
    ).fetchone()
    if row:
        return dict(row)

    emp = conn.execute(
        "SELECT hire_date FROM employees WHERE id=?", (emp_id,)
    ).fetchone()
    hire_date = emp["hire_date"] if emp and emp["hire_date"] else None
    ref = date(year, 12, 31)
    if hire_date:
        granted = calc_annual_leave(hire_date, ref)
    else:
        granted = 15

    conn.execute(
        """INSERT OR IGNORE INTO leave_accruals (employee_id, accrual_year, granted, used, basis)
           VALUES (?, ?, ?, 0, 'auto')""",
        (emp_id, year, granted),
    )
    conn.commit()
    return dict(conn.execute(
        "SELECT * FROM leave_accruals WHERE employee_id=? AND accrual_year=?",
        (emp_id, year),
    ).fetchone())


def get_leave_balance(conn, emp_id, year):
    row = conn.execute(
        "SELECT granted, used FROM leave_accruals WHERE employee_id=? AND accrual_year=?",
        (emp_id, year),
    ).fetchone()
    if not row:
        acc = ensure_accrual(conn, emp_id, year)
        granted = acc["granted"]
        used = acc["used"]
    else:
        granted = row["granted"]
        used = row["used"]
    return granted, used, round(granted - used, 1)
