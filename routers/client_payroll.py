from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_client_hr_with_company, templates
from core.payroll import build_payslip, calc_overtime_pay, get_rates
from core.attendance import is_month_closed
from core.tz import now_kst
from routers.erp_accounting import _create_payroll_slip

router = APIRouter(prefix="/client")


def _payroll_month(request):
    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
        month = int(request.query_params.get("month", now.month))
    except ValueError:
        year, month = now.year, now.month
    return year, month


@router.get("/payroll", response_class=HTMLResponse)
async def payroll_list(
    request: Request,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    year, month = _payroll_month(request)

    company_id = user["company_id"]
    workers = conn.execute(
        "SELECT id, name, employee_no, dept, position FROM employees WHERE company_id=? AND status='active'",
        (company_id,),
    ).fetchall()
    workers = [dict(w) for w in workers]

    for w in workers:
        ps = conn.execute(
            "SELECT status, gross_pay, total_deduction, net_pay FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
            (w["id"], year, month),
        ).fetchone()
        if ps:
            w["payslip_status"] = ps["status"]
            w["gross_pay"] = ps["gross_pay"]
            w["net_pay"] = ps["net_pay"]
            w["total_deduction"] = ps["total_deduction"]
        else:
            w["payslip_status"] = None

    has_draft = any(w["payslip_status"] == "draft" for w in workers)
    all_confirmed = all(w["payslip_status"] == "confirmed" for w in workers if w["payslip_status"])

    att_closed = is_month_closed(conn, year, month, company_id)

    company = conn.execute("SELECT name FROM client_companies WHERE id=?", (company_id,)).fetchone()
    company_name = company["name"] if company else ""

    pm = month - 1 if month > 1 else 12
    py_ = year if month > 1 else year - 1
    nm = month + 1 if month < 12 else 1
    ny = year if month < 12 else year + 1

    return templates.TemplateResponse(
        request=request, name="client/payroll.html", context={
            "request": request,
            "page_title": "급여 관리",
            "user_name": user["name"],
            "workers": workers,
            "year": year,
            "month": month,
            "company_name": company_name,
            "has_draft": has_draft,
            "all_confirmed": all_confirmed,
            "att_closed": att_closed,
            "pm": pm, "py": py_, "nm": nm, "ny": ny,
        }
    )


@router.get("/payroll/{employee_id}", response_class=HTMLResponse)
async def payroll_edit(
    request: Request,
    employee_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    year, month = _payroll_month(request)

    company_id = user["company_id"]
    worker = conn.execute(
        "SELECT id, name, employee_no, dept, position, company_id, base_salary, monthly_work_hours FROM employees WHERE id=?",
        (employee_id,),
    ).fetchone()
    if not worker or worker["company_id"] != company_id:
        return RedirectResponse(url="/client/payroll", status_code=303)
    worker = dict(worker)

    payslip = conn.execute(
        "SELECT * FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
        (employee_id, year, month),
    ).fetchone()
    payslip = dict(payslip) if payslip else None

    prev_payslip = None
    pm = month - 1
    py = year
    if pm < 1:
        pm, py = 12, year - 1
    prev = conn.execute(
        "SELECT base_salary, overtime_pay, disability_allowance, meal_allowance FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
        (employee_id, py, pm),
    ).fetchone()
    if prev:
        prev_payslip = dict(prev)

    is_locked = payslip and payslip.get("status") == "confirmed"

    ot_row = conn.execute(
        """SELECT COALESCE(SUM(overtime_minutes),0) as total_ot
           FROM attendance WHERE employee_id=?
           AND work_date BETWEEN ? AND ?""",
        (employee_id, f"{year}-{month:02d}-01", f"{year}-{month:02d}-31"),
    ).fetchone()
    total_ot_minutes = ot_row["total_ot"] if ot_row else 0
    suggested_overtime_pay = calc_overtime_pay(
        worker["base_salary"] or 0,
        worker["monthly_work_hours"] or 0,
        total_ot_minutes,
    )

    att_closed = is_month_closed(conn, year, month, company_id)

    pm = month - 1 if month > 1 else 12
    py_ = year if month > 1 else year - 1
    nm = month + 1 if month < 12 else 1
    ny = year if month < 12 else year + 1

    tax_free_meal = min(payslip.get("meal_allowance") or 0, 200000) if payslip else 0

    return templates.TemplateResponse(
        request=request, name="client/payroll_edit.html", context={
            "request": request,
            "page_title": f"{worker['name']} 급여 입력",
            "user_name": user["name"],
            "worker": worker,
            "payslip": payslip,
            "prev_payslip": prev_payslip,
            "year": year,
            "month": month,
            "is_locked": is_locked,
            "att_closed": att_closed,
            "total_ot_minutes": total_ot_minutes,
            "suggested_overtime_pay": suggested_overtime_pay,
            "pm": pm, "py": py_, "nm": nm, "ny": ny,
            "tax_free_meal": tax_free_meal,
        }
    )


@router.post("/payroll/confirm")
async def payroll_confirm(
    request: Request,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    form = await request.form()
    year = int(form.get("year", now_kst().year))
    month = int(form.get("month", now_kst().month))

    company_id = user["company_id"]

    if not is_month_closed(conn, year, month, company_id):
        return RedirectResponse(
            url=f"/client/payroll?year={year}&month={month}&error=att_not_closed",
            status_code=303,
        )

    emp_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM employees WHERE company_id=? AND status='active'", (company_id,)
    ).fetchall()]
    if emp_ids:
        placeholders = ",".join("?" * len(emp_ids))
        conn.execute(
            f"UPDATE payslips SET status='confirmed' WHERE employee_id IN ({placeholders}) AND pay_year=? AND pay_month=? AND status='draft'",
            (*emp_ids, year, month),
        )

        uid = user["id"]
        confirmed = conn.execute(
            f"""SELECT p.*, e.name as employee_name
                FROM payslips p JOIN employees e ON p.employee_id=e.id
                WHERE p.employee_id IN ({placeholders}) AND p.pay_year=? AND p.pay_month=? AND p.status='confirmed'""",
            (*emp_ids, year, month),
        ).fetchall()
        for ps in confirmed:
            ps = dict(ps)
            existing = conn.execute(
                "SELECT id FROM erp_docs WHERE doc_number LIKE ? AND title LIKE ?",
                (f"PAY-{year}-%", f"%{ps['employee_name']} {year}.{month:02d}%"),
            ).fetchone()
            if not existing:
                _create_payroll_slip(conn, ps, ps["employee_name"], uid)

        conn.commit()

    return RedirectResponse(url=f"/client/payroll?year={year}&month={month}", status_code=303)


@router.post("/payroll/{employee_id}")
async def payroll_save(
    request: Request,
    employee_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
    base_salary: int = Form(...),
    overtime_pay: int = Form(0),
    disability_allowance: int = Form(0),
    meal_allowance: int = Form(0),
    year: int = Form(...),
    month: int = Form(...),
):
    if any(v < 0 for v in (base_salary, overtime_pay, disability_allowance, meal_allowance)):
        return RedirectResponse(
            url=f"/client/payroll/{employee_id}?year={year}&month={month}&error=negative",
            status_code=303,
        )

    company_id = user["company_id"]
    worker = conn.execute(
        "SELECT id, company_id FROM employees WHERE id=?", (employee_id,)
    ).fetchone()
    if not worker or worker["company_id"] != company_id:
        return RedirectResponse(url="/client/payroll", status_code=303)

    existing = conn.execute(
        "SELECT id, status FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
        (employee_id, year, month),
    ).fetchone()
    if existing and existing["status"] == "confirmed":
        return RedirectResponse(url=f"/client/payroll?year={year}&month={month}", status_code=303)

    rates = get_rates(conn, year, month)
    ps = build_payslip(base_salary, overtime_pay, disability_allowance, meal_allowance, rates)
    pay_date = f"{year}-{month:02d}-25"

    if existing:
        conn.execute("""
            UPDATE payslips SET base_salary=?, overtime_pay=?, disability_allowance=?,
                meal_allowance=?, gross_pay=?, national_pension=?, health_insurance=?,
                long_care=?, employment_insurance=?, income_tax=?, resident_tax=?,
                total_deduction=?, net_pay=?, pay_date=?, status='draft'
            WHERE id=?
        """, (ps["base_salary"], ps["overtime_pay"], ps["disability_allowance"],
              ps["meal_allowance"], ps["gross_pay"], ps["national_pension"],
              ps["health_insurance"], ps["long_care"], ps["employment_insurance"],
              ps["income_tax"], ps["resident_tax"], ps["total_deduction"],
              ps["net_pay"], pay_date, existing["id"]))
    else:
        conn.execute("""
            INSERT INTO payslips (employee_id, pay_year, pay_month, base_salary, overtime_pay,
                disability_allowance, meal_allowance, gross_pay, national_pension,
                health_insurance, long_care, employment_insurance, income_tax, resident_tax,
                total_deduction, net_pay, pay_date, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft',datetime('now','localtime'))
        """, (employee_id, year, month, ps["base_salary"], ps["overtime_pay"],
              ps["disability_allowance"], ps["meal_allowance"], ps["gross_pay"],
              ps["national_pension"], ps["health_insurance"], ps["long_care"],
              ps["employment_insurance"], ps["income_tax"], ps["resident_tax"],
              ps["total_deduction"], ps["net_pay"], pay_date))

    conn.commit()

    return RedirectResponse(url=f"/client/payroll?year={year}&month={month}", status_code=303)
