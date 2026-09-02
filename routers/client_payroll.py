from core.tz import now_kst

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_client_hr_with_company, templates
from core.payroll import build_payslip

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

    company = conn.execute("SELECT name FROM client_companies WHERE id=?", (company_id,)).fetchone()
    company_name = company["name"] if company else ""

    return templates.TemplateResponse(
        request=request, name="client/payroll.html", context={
            "request": request,
            "page_title": "급여 관리",
            "user_name": user["user_name"],
            "workers": workers,
            "year": year,
            "month": month,
            "company_name": company_name,
            "has_draft": has_draft,
            "all_confirmed": all_confirmed,
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
        "SELECT id, name, employee_no, dept, position, company_id FROM employees WHERE id=?",
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

    return templates.TemplateResponse(
        request=request, name="client/payroll_edit.html", context={
            "request": request,
            "page_title": f"{worker['name']} 급여 입력",
            "user_name": user["user_name"],
            "worker": worker,
            "payslip": payslip,
            "prev_payslip": prev_payslip,
            "year": year,
            "month": month,
            "is_locked": is_locked,
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
    emp_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM employees WHERE company_id=? AND status='active'", (company_id,)
    ).fetchall()]
    if emp_ids:
        placeholders = ",".join("?" * len(emp_ids))
        conn.execute(
            f"UPDATE payslips SET status='confirmed' WHERE employee_id IN ({placeholders}) AND pay_year=? AND pay_month=? AND status='draft'",
            (*emp_ids, year, month),
        )
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

    ps = build_payslip(base_salary, overtime_pay, disability_allowance, meal_allowance)
    pay_date = f"{year}-{month:02d}-25"

    if existing:
        conn.execute("""
            UPDATE payslips SET base_salary=?, overtime_pay=?, disability_allowance=?,
                meal_allowance=?, gross_pay=?, national_pension=?, health_insurance=?,
                employment_insurance=?, income_tax=?, resident_tax=?, total_deduction=?,
                net_pay=?, pay_date=?, status='draft'
            WHERE id=?
        """, (ps["base_salary"], ps["overtime_pay"], ps["disability_allowance"],
              ps["meal_allowance"], ps["gross_pay"], ps["national_pension"],
              ps["health_insurance"], ps["employment_insurance"], ps["income_tax"],
              ps["resident_tax"], ps["total_deduction"], ps["net_pay"], pay_date,
              existing["id"]))
    else:
        conn.execute("""
            INSERT INTO payslips (employee_id, pay_year, pay_month, base_salary, overtime_pay,
                disability_allowance, meal_allowance, gross_pay, national_pension,
                health_insurance, employment_insurance, income_tax, resident_tax,
                total_deduction, net_pay, pay_date, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'draft',datetime('now','localtime'))
        """, (employee_id, year, month, ps["base_salary"], ps["overtime_pay"],
              ps["disability_allowance"], ps["meal_allowance"], ps["gross_pay"],
              ps["national_pension"], ps["health_insurance"], ps["employment_insurance"],
              ps["income_tax"], ps["resident_tax"], ps["total_deduction"],
              ps["net_pay"], pay_date))

    conn.commit()

    return RedirectResponse(url=f"/client/payroll?year={year}&month={month}", status_code=303)
