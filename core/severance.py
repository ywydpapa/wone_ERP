from datetime import date


def calc_severance(conn, emp_id, resign_date=None):
    emp = conn.execute(
        "SELECT hire_date, resign_date FROM employees WHERE id=?", (emp_id,)
    ).fetchone()
    if not emp:
        return None

    rd = resign_date or emp["resign_date"]
    hd = emp["hire_date"]
    if not rd or not hd:
        return None

    resign_dt = date.fromisoformat(rd)
    hire_dt = date.fromisoformat(hd)
    tenure_days = (resign_dt - hire_dt).days
    if tenure_days < 365:
        return {"avg_salary": 0, "tenure_days": tenure_days, "amount": 0}

    slips = conn.execute(
        """SELECT gross_pay FROM payslips
           WHERE employee_id=?
           ORDER BY pay_year DESC, pay_month DESC
           LIMIT 3""",
        (emp_id,),
    ).fetchall()

    if slips:
        avg_salary = sum(r["gross_pay"] for r in slips) // len(slips)
    else:
        base = conn.execute(
            "SELECT base_salary FROM employees WHERE id=?", (emp_id,)
        ).fetchone()
        avg_salary = base["base_salary"] if base else 0

    amount = int(avg_salary * tenure_days / 365)
    return {"avg_salary": avg_salary, "tenure_days": tenure_days, "amount": amount}
