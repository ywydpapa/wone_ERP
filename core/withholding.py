import calendar

from core.crypto import dec_rno

# 식대(P01)는 2023.2.28 개정 이후 제출비과세. 총지급액 포함
SUBMIT_FREE_CODES = {"P01"}

# 근로소득 간이지급명세서 매월 제출 시행연도. 2026년까지는 반기 제출 유지, 2027.1.1 지급분부터 매월
MONTHLY_STATEMENT_YEAR = 2027


def _split_amount(taxable, tax_free_limit, amount):
    if tax_free_limit:
        free = min(amount, tax_free_limit)
        taxed = max(0, amount - tax_free_limit)
    elif taxable:
        free, taxed = 0, amount
    else:
        free, taxed = amount, 0
    return taxed, free


def _items_by_payslip(conn, payslip_ids):
    if not payslip_ids:
        return {}
    ph = ",".join("?" * len(payslip_ids))
    rows = conn.execute(
        f"""SELECT pi.payslip_id, pi.amount, it.taxable, it.tax_free_limit, it.tax_free_code, it.name, it.bonus
            FROM payslip_items pi JOIN pay_items it ON it.id = pi.item_id
            WHERE pi.payslip_id IN ({ph}) AND it.kind='지급'""",
        payslip_ids,
    ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["payslip_id"], []).append(r)
    return out


def taxable_by_payslip(conn, payslip_ids):
    items = _items_by_payslip(conn, payslip_ids)
    return {
        pid: sum(_split_amount(it["taxable"], it["tax_free_limit"], it["amount"])[0] for it in items.get(pid, []))
        for pid in payslip_ids
    }


def due_date_next_month(year, month, day=10):
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{year}-{month:02d}-{day:02d}"


def get_report(conn, company_id, year, month):
    period = f"{year}-{month:02d}"
    rows = conn.execute(
        """SELECT p.*, e.id AS emp_id, e.name AS emp_name, e.resident_no, e.employee_no
           FROM payslips p JOIN employees e ON e.id = p.employee_id
           WHERE e.company_id IS ? AND p.status='confirmed'
             AND (
               (p.pay_date IS NOT NULL AND p.pay_date != '' AND substr(p.pay_date,1,7)=?)
               OR ((p.pay_date IS NULL OR p.pay_date='') AND p.pay_year=? AND p.pay_month=?)
             )
           ORDER BY e.employee_no, e.name""",
        (company_id, period, year, month),
    ).fetchall()
    rows = [dict(r) for r in rows]
    for r in rows:
        r["resident_no"] = dec_rno(r["resident_no"])

    items_by_ps = _items_by_payslip(conn, [r["id"] for r in rows])
    for r in rows:
        taxable = submit_free = other_free = 0
        for it in items_by_ps.get(r["id"], []):
            taxed, free = _split_amount(it["taxable"], it["tax_free_limit"], it["amount"])
            taxable += taxed
            if free:
                if (it["tax_free_code"] or "") in SUBMIT_FREE_CODES:
                    submit_free += free
                else:
                    other_free += free
        r["taxable_pay"] = taxable
        r["submit_free_pay"] = submit_free
        r["nonsubmit_free_pay"] = other_free
        r["total_pay"] = taxable + submit_free

    return {
        "rows": rows,
        "headcount": len(rows),
        "sum_pay": sum(r["total_pay"] for r in rows),
        "sum_tax": sum(r["income_tax"] or 0 for r in rows),
        "sum_resident": sum(r["resident_tax"] or 0 for r in rows),
        "due_date": due_date_next_month(year, month),
    }


def get_employee_yearly(conn, emp_id, year):
    rows = conn.execute(
        """SELECT * FROM payslips WHERE employee_id=? AND pay_year=? AND status='confirmed'
           ORDER BY pay_month""",
        (emp_id, year),
    ).fetchall()
    rows = [dict(r) for r in rows]

    items_by_ps = _items_by_payslip(conn, [r["id"] for r in rows])
    free_labels = {}
    for r in rows:
        salary = bonus = 0
        free_by_code = {}
        for it in items_by_ps.get(r["id"], []):
            taxed, free = _split_amount(it["taxable"], it["tax_free_limit"], it["amount"])
            if it["bonus"]:
                bonus += taxed
            else:
                salary += taxed
            if free:
                code = it["tax_free_code"] or it["name"]
                free_by_code[code] = free_by_code.get(code, 0) + free
                free_labels.setdefault(code, it["name"])
        r["salary"] = salary
        r["bonus"] = bonus
        r["taxable_total"] = salary + bonus
        r["free_by_code"] = free_by_code
        r["health_total"] = (r["health_insurance"] or 0) + (r["long_care"] or 0)

    codes = list(free_labels.keys())
    totals = {
        "salary": sum(r["salary"] for r in rows),
        "bonus": sum(r["bonus"] for r in rows),
        "taxable_total": sum(r["taxable_total"] for r in rows),
        "national_pension": sum(r["national_pension"] or 0 for r in rows),
        "health_total": sum(r["health_total"] for r in rows),
        "employment_insurance": sum(r["employment_insurance"] or 0 for r in rows),
        "income_tax": sum(r["income_tax"] or 0 for r in rows),
        "resident_tax": sum(r["resident_tax"] or 0 for r in rows),
    }
    for code in codes:
        totals[code] = sum(r["free_by_code"].get(code, 0) for r in rows)

    return {"rows": rows, "codes": codes, "free_labels": free_labels, "totals": totals}


def half_range(year, half):
    if half == 2:
        return f"{year}-07-01", f"{year}-12-31", 7, 12
    return f"{year}-01-01", f"{year}-06-30", 1, 6


def simple_statement_due(year, half):
    return f"{year}-07-31" if half == 1 else f"{year + 1}-01-31"


def simple_due(year, month):
    y, m = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def simple_monthly(year):
    return year >= MONTHLY_STATEMENT_YEAR


def _simple_rows(conn, company_id, start, end, year, m1, m2):
    rows = conn.execute(
        """SELECT e.id AS emp_id, e.name, e.resident_no, e.hire_date, e.resign_date,
                  p.id AS payslip_id
           FROM payslips p JOIN employees e ON e.id = p.employee_id
           WHERE e.company_id IS ? AND p.status='confirmed'
             AND (
               (p.pay_date IS NOT NULL AND p.pay_date != '' AND p.pay_date BETWEEN ? AND ?)
               OR ((p.pay_date IS NULL OR p.pay_date='') AND p.pay_year=? AND p.pay_month BETWEEN ? AND ?)
             )
           ORDER BY e.employee_no, e.name""",
        (company_id, start, end, year, m1, m2),
    ).fetchall()
    rows = [dict(r) for r in rows]

    taxable = taxable_by_payslip(conn, [r["payslip_id"] for r in rows])
    by_emp = {}
    for r in rows:
        emp = by_emp.setdefault(r["emp_id"], {
            "name": r["name"], "resident_no": dec_rno(r["resident_no"]),
            "hire_date": r["hire_date"], "resign_date": r["resign_date"],
            "taxable_total": 0,
        })
        emp["taxable_total"] += taxable[r["payslip_id"]]

    out = []
    for emp_id, e in by_emp.items():
        work_start = max(e["hire_date"] or start, start)
        work_end = min(e["resign_date"], end) if e["resign_date"] else end
        out.append({"emp_id": emp_id, **e, "work_start": work_start, "work_end": work_end})
    out.sort(key=lambda r: r["name"])
    return out


def get_simple_statement(conn, company_id, year, half):
    start, end, m1, m2 = half_range(year, half)
    rows = _simple_rows(conn, company_id, start, end, year, m1, m2)
    return {"rows": rows, "start": start, "end": end, "due_date": simple_statement_due(year, half)}


def get_simple_statement_month(conn, company_id, year, month):
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    rows = _simple_rows(conn, company_id, start, end, year, month, month)
    return {"rows": rows, "start": start, "end": end, "due_date": simple_due(year, month)}
