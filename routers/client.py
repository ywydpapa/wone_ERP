from core.tz import now_kst

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from core.db import get_sqlite
from core.deps import check_login, get_current_user, templates
from core.payroll import build_payslip
from core.leave import (
    LEAVE_TYPES, get_pending_leaves, get_all_leaves,
    get_leave_balance, approve_leave, reject_leave,
    get_month_leaves, build_leave_calendar,
)
from core.attendance import (
    get_company_id_for_client,
    get_company_workers,
    get_attendance_records,
    get_attendance_summary,
    get_worker_detail,
    get_worker_month_records,
    build_calendar_data,
    worker_month_summary,
    prev_next_month,
    available_months,
)

router = APIRouter(prefix="/client")


def _require_client(request: Request, allowed_roles=None):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    user = get_current_user(request)
    if user["user_role"] != "client":
        return RedirectResponse(url="/", status_code=303)
    if allowed_roles:
        client_role = request.session.get("client_role", "all")
        if client_role != "all" and client_role not in allowed_roles:
            return RedirectResponse(url="/", status_code=303)
    return None


@router.get("/work-status", response_class=HTMLResponse)
async def work_status(request: Request):
    guard = _require_client(request)
    if guard:
        return guard
    user = get_current_user(request)
    return templates.TemplateResponse(
        request=request, name="client/work_status.html", context={
            "request": request,
            "page_title": "업무 진행 현황",
            "user_name": user["user_name"],
        }
    )


@router.get("/attendance", response_class=HTMLResponse)
async def attendance(request: Request):
    guard = _require_client(request)
    if guard:
        return guard
    user = get_current_user(request)

    month = request.query_params.get("month", now_kst().strftime("%Y-%m"))
    status_filter = request.query_params.get("status", "")

    conn = get_sqlite()
    try:
        company_id = get_company_id_for_client(conn, user["user_id"])
        workers = get_company_workers(conn, company_id) if company_id else []
        emp_ids = [w["id"] for w in workers]
        records = get_attendance_records(conn, emp_ids, month)
        if status_filter:
            records = [r for r in records if r["status"] == status_filter]
        summary = get_attendance_summary(records, len(workers))
    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request, name="client/attendance.html", context={
            "request": request,
            "page_title": "근태 관리",
            "user_name": user["user_name"],
            "records": records,
            "summary": summary,
            "workers": workers,
            "current_month": month,
            "status_filter": status_filter,
            "months": available_months(),
        }
    )


@router.get("/attendance/{employee_id}", response_class=HTMLResponse)
async def attendance_detail(request: Request, employee_id: int):
    guard = _require_client(request)
    if guard:
        return guard
    user = get_current_user(request)

    month = request.query_params.get("month", now_kst().strftime("%Y-%m"))
    conn = get_sqlite()
    try:
        company_id = get_company_id_for_client(conn, user["user_id"])
        worker = get_worker_detail(conn, employee_id)
        if not worker or worker.get("company_id") != company_id:
            return RedirectResponse(url="/client/attendance", status_code=303)
        records = get_worker_month_records(conn, employee_id, month)
        summary = worker_month_summary(records)
        cal = build_calendar_data(records, month)
        prev_m, next_m = prev_next_month(month)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="client/attendance_detail.html",
        context={
            "request": request,
            "page_title": f"{worker['name']} 근태 상세",
            "user_name": user["user_name"],
            "worker": worker,
            "records": records,
            "summary": summary,
            "cal": cal,
            "current_month": month,
            "prev_month": prev_m,
            "next_month": next_m,
            "back_url": "/client/attendance",
        }
    )


# 급여 관리

def _payroll_month(request):
    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
        month = int(request.query_params.get("month", now.month))
    except ValueError:
        year, month = now.year, now.month
    return year, month


@router.get("/payroll", response_class=HTMLResponse)
async def payroll_list(request: Request):
    guard = _require_client(request, allowed_roles=("hr",))
    if guard:
        return guard
    user = get_current_user(request)
    year, month = _payroll_month(request)

    conn = get_sqlite()
    try:
        company_id = get_company_id_for_client(conn, user["user_id"])
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
    finally:
        conn.close()

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
async def payroll_edit(request: Request, employee_id: int):
    guard = _require_client(request, allowed_roles=("hr",))
    if guard:
        return guard
    user = get_current_user(request)
    year, month = _payroll_month(request)

    conn = get_sqlite()
    try:
        company_id = get_company_id_for_client(conn, user["user_id"])
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
    finally:
        conn.close()

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
async def payroll_confirm(request: Request):
    guard = _require_client(request, allowed_roles=("hr",))
    if guard:
        return guard
    user = get_current_user(request)

    form = await request.form()
    year = int(form.get("year", now_kst().year))
    month = int(form.get("month", now_kst().month))

    conn = get_sqlite()
    try:
        company_id = get_company_id_for_client(conn, user["user_id"])
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
    finally:
        conn.close()

    return RedirectResponse(url=f"/client/payroll?year={year}&month={month}", status_code=303)


@router.post("/payroll/{employee_id}")
async def payroll_save(
    request: Request,
    employee_id: int,
    base_salary: int = Form(...),
    overtime_pay: int = Form(0),
    disability_allowance: int = Form(0),
    meal_allowance: int = Form(0),
    year: int = Form(...),
    month: int = Form(...),
):
    guard = _require_client(request, allowed_roles=("hr",))
    if guard:
        return guard
    user = get_current_user(request)

    if any(v < 0 for v in (base_salary, overtime_pay, disability_allowance, meal_allowance)):
        return RedirectResponse(
            url=f"/client/payroll/edit/{employee_id}?year={year}&month={month}&error=negative",
            status_code=303,
        )

    conn = get_sqlite()
    try:
        company_id = get_company_id_for_client(conn, user["user_id"])
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
    finally:
        conn.close()

    return RedirectResponse(url=f"/client/payroll?year={year}&month={month}", status_code=303)



@router.get("/leave/calendar", response_class=HTMLResponse)
async def leave_calendar(request: Request):
    guard = _require_client(request, allowed_roles=("hr",))
    if guard:
        return guard
    user = get_current_user(request)

    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
        month = int(request.query_params.get("month", now.month))
    except ValueError:
        year, month = now.year, now.month

    conn = get_sqlite()
    try:
        company_id = get_company_id_for_client(conn, user["user_id"])
        leaves = get_month_leaves(conn, company_id, year, month)
        weeks, leave_map = build_leave_calendar(leaves, year, month)
        company = conn.execute(
            "SELECT name FROM client_companies WHERE id=?", (company_id,)
        ).fetchone()
        company_name = company["name"] if company else ""
    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request, name="client/leave_calendar.html", context={
            "request": request,
            "page_title": "휴가 캘린더",
            "user_name": user["user_name"],
            "company_name": company_name,
            "year": year,
            "month": month,
            "weeks": weeks,
            "leave_map": leave_map,
            "weekday_names": ["일", "월", "화", "수", "목", "금", "토"],
        }
    )


@router.get("/leave", response_class=HTMLResponse)
async def leave_list(request: Request):
    guard = _require_client(request, allowed_roles=("hr",))
    if guard:
        return guard
    user = get_current_user(request)
    status_filter = request.query_params.get("status", "")

    conn = get_sqlite()
    try:
        company_id = get_company_id_for_client(conn, user["user_id"])
        if status_filter == "pending":
            leaves = get_pending_leaves(conn, company_id)
        else:
            leaves = get_all_leaves(conn, company_id, status_filter or None)
        pending_count = len(get_pending_leaves(conn, company_id))
        leaves = [dict(r) for r in leaves]
        for r in leaves:
            r["leave_type_label"] = LEAVE_TYPES.get(r["leave_type"], {}).get("label", r["leave_type"])
        company = conn.execute(
            "SELECT name FROM client_companies WHERE id=?", (company_id,)
        ).fetchone()
        company_name = company["name"] if company else ""
    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request, name="client/leave_list.html", context={
            "request": request,
            "page_title": "휴가 관리",
            "user_name": user["user_name"],
            "company_name": company_name,
            "leaves": leaves,
            "leave_types": LEAVE_TYPES,
            "status_filter": status_filter,
            "pending_count": pending_count,
            "total_count": len(leaves),
        }
    )


@router.post("/leave/{leave_id}/approve")
async def leave_approve(request: Request, leave_id: int):
    guard = _require_client(request, allowed_roles=("hr",))
    if guard:
        return guard
    user = get_current_user(request)

    conn = get_sqlite()
    try:
        company_id = get_company_id_for_client(conn, user["user_id"])
        lr = conn.execute(
            "SELECT e.company_id FROM leave_requests lr JOIN employees e ON lr.employee_id=e.id WHERE lr.id=?",
            (leave_id,),
        ).fetchone()
        if lr and lr["company_id"] == company_id:
            approve_leave(conn, leave_id, user["user_id"])
    finally:
        conn.close()

    return RedirectResponse(url="/client/leave", status_code=303)


@router.post("/leave/{leave_id}/reject")
async def leave_reject(request: Request, leave_id: int):
    guard = _require_client(request, allowed_roles=("hr",))
    if guard:
        return guard
    user = get_current_user(request)

    form = await request.form()
    reason = form.get("reason", "")

    conn = get_sqlite()
    try:
        company_id = get_company_id_for_client(conn, user["user_id"])
        lr = conn.execute(
            "SELECT e.company_id FROM leave_requests lr JOIN employees e ON lr.employee_id=e.id WHERE lr.id=?",
            (leave_id,),
        ).fetchone()
        if lr and lr["company_id"] == company_id:
            reject_leave(conn, leave_id, user["user_id"], reason)
    finally:
        conn.close()

    return RedirectResponse(url="/client/leave", status_code=303)
