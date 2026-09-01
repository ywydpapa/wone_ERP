from core.tz import now_kst
from datetime import date

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_client, require_client_hr, templates
from core.payroll import build_payslip
from core.leave import (
    LEAVE_TYPES, get_pending_leaves, get_all_leaves,
    get_leave_balance, approve_leave, reject_leave,
    get_month_leaves, build_leave_calendar,
)
from core.approval import get_approval, approve, reject
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

DISABILITY_TYPE_LABELS = {
    "physical": "지체", "visual": "시각", "hearing": "청각",
    "intellectual": "지적", "mental": "정신", "brain": "뇌병변",
    "autism": "자폐성", "kidney": "신장", "heart": "심장",
    "respiratory": "호흡기", "liver": "간", "facial": "안면",
    "intestinal": "장루요루", "epilepsy": "뇌전증",
}

DISABILITY_GRADE_LABELS = {
    "severe": "중증", "mild": "경증",
}

ACCOMMODATION_CATEGORY_LABELS = {
    "assistive_tech": "보조기기 지원",
    "work_assistant": "근로지원인",
    "workspace_adjust": "작업환경 개선",
}

ACCOMMODATION_STATUS_LABELS = {
    "pending": "대기",
    "approved": "승인",
    "rejected": "반려",
}

URGENCY_LABELS = {
    "normal": "일반",
    "high": "높음",
    "urgent": "긴급",
}


@router.get("/workers", response_class=HTMLResponse)
async def worker_list(
    request: Request,
    user: dict = Depends(require_client()),
    conn=Depends(get_db),
):
    status_filter = request.query_params.get("status", "")
    search_query = request.query_params.get("q", "")

    company_id = get_company_id_for_client(conn, user["user_id"])
    sql = """SELECT id, name, employee_no, dept, position, hire_date, status,
                    disability_type, disability_grade
             FROM employees WHERE company_id=?"""
    params = [company_id]
    if status_filter:
        sql += " AND status=?"
        params.append(status_filter)
    if search_query:
        sql += " AND (name LIKE ? OR employee_no LIKE ?)"
        params += [f"%{search_query}%", f"%{search_query}%"]
    sql += " ORDER BY name"
    rows = conn.execute(sql, params).fetchall()
    workers = [dict(r) for r in rows]
    for w in workers:
        w["disability_type_label"] = DISABILITY_TYPE_LABELS.get(w["disability_type"], w["disability_type"] or "")
        w["disability_grade_label"] = DISABILITY_GRADE_LABELS.get(w["disability_grade"], w["disability_grade"] or "")
    total_count = len(workers)
    active_count = sum(1 for w in workers if w["status"] == "active")

    return templates.TemplateResponse(
        request=request, name="client/workers.html", context={
            "request": request,
            "page_title": "근로자 관리",
            "user_name": user["user_name"],
            "workers": workers,
            "total_count": total_count,
            "active_count": active_count,
            "status_filter": status_filter,
            "search_query": search_query,
            "disability_type_labels": DISABILITY_TYPE_LABELS,
        }
    )


@router.get("/workers/{employee_id}", response_class=HTMLResponse)
async def worker_detail(
    request: Request,
    employee_id: int,
    user: dict = Depends(require_client()),
    conn=Depends(get_db),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    row = conn.execute(
        """SELECT e.*, c.name as company_name
           FROM employees e
           LEFT JOIN client_companies c ON e.company_id = c.id
           WHERE e.id=?""",
        (employee_id,),
    ).fetchone()
    if not row or row["company_id"] != company_id:
        return RedirectResponse(url="/client/workers", status_code=303)
    worker = dict(row)
    worker["disability_type_label"] = DISABILITY_TYPE_LABELS.get(worker["disability_type"], worker["disability_type"] or "")
    worker["disability_grade_label"] = DISABILITY_GRADE_LABELS.get(worker["disability_grade"], worker["disability_grade"] or "")

    recent_attendance = conn.execute(
        """SELECT work_date, clock_in, clock_out, status, notes
           FROM attendance WHERE employee_id=?
           ORDER BY work_date DESC LIMIT 5""",
        (employee_id,),
    ).fetchall()
    recent_attendance = [dict(r) for r in recent_attendance]

    active_accom_count = conn.execute(
        """SELECT COUNT(*) FROM accommodation_requests
           WHERE employee_id=? AND status='pending'""",
        (employee_id,),
    ).fetchone()[0]

    leave_total = worker.get("annual_leave_total") or 0
    leave_used = worker.get("annual_leave_used") or 0
    leave_remaining = max(0, leave_total - leave_used)
    leave_pct = int(leave_used / leave_total * 100) if leave_total else 0

    return templates.TemplateResponse(
        request=request, name="client/worker_detail.html", context={
            "request": request,
            "page_title": f"{worker['name']} 프로필",
            "user_name": user["user_name"],
            "worker": worker,
            "recent_attendance": recent_attendance,
            "active_accom_count": active_accom_count,
            "leave_total": leave_total,
            "leave_used": leave_used,
            "leave_remaining": leave_remaining,
            "leave_pct": leave_pct,
        }
    )


@router.get("/attendance", response_class=HTMLResponse)
async def attendance(
    request: Request,
    user: dict = Depends(require_client()),
    conn=Depends(get_db),
):
    month = request.query_params.get("month", now_kst().strftime("%Y-%m"))
    status_filter = request.query_params.get("status", "")

    company_id = get_company_id_for_client(conn, user["user_id"])
    workers = get_company_workers(conn, company_id) if company_id else []
    emp_ids = [w["id"] for w in workers]
    records = get_attendance_records(conn, emp_ids, month)
    if status_filter:
        records = [r for r in records if r["status"] == status_filter]
    summary = get_attendance_summary(records, len(workers))

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
async def attendance_detail(
    request: Request,
    employee_id: int,
    user: dict = Depends(require_client()),
    conn=Depends(get_db),
):
    month = request.query_params.get("month", now_kst().strftime("%Y-%m"))
    company_id = get_company_id_for_client(conn, user["user_id"])
    worker = get_worker_detail(conn, employee_id)
    if not worker or worker.get("company_id") != company_id:
        return RedirectResponse(url="/client/attendance", status_code=303)
    records = get_worker_month_records(conn, employee_id, month)
    summary = worker_month_summary(records)
    cal = build_calendar_data(records, month)
    prev_m, next_m = prev_next_month(month)

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
async def payroll_list(
    request: Request,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    year, month = _payroll_month(request)

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
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    year, month = _payroll_month(request)

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
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    form = await request.form()
    year = int(form.get("year", now_kst().year))
    month = int(form.get("month", now_kst().month))

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

    return RedirectResponse(url=f"/client/payroll?year={year}&month={month}", status_code=303)


@router.post("/payroll/{employee_id}")
async def payroll_save(
    request: Request,
    employee_id: int,
    user: dict = Depends(require_client_hr),
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

    return RedirectResponse(url=f"/client/payroll?year={year}&month={month}", status_code=303)


@router.get("/leave/calendar", response_class=HTMLResponse)
async def leave_calendar(
    request: Request,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
        month = int(request.query_params.get("month", now.month))
    except ValueError:
        year, month = now.year, now.month

    company_id = get_company_id_for_client(conn, user["user_id"])
    leaves = get_month_leaves(conn, company_id, year, month)
    weeks, leave_map = build_leave_calendar(leaves, year, month)
    company = conn.execute(
        "SELECT name FROM client_companies WHERE id=?", (company_id,)
    ).fetchone()
    company_name = company["name"] if company else ""

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


@router.get("/leave/balance", response_class=HTMLResponse)
async def leave_balance(
    request: Request,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    rows = conn.execute(
        """SELECT id, name, employee_no, dept,
                  annual_leave_total, annual_leave_used
           FROM employees
           WHERE company_id=? AND status='active'
           ORDER BY name""",
        (company_id,),
    ).fetchall()
    workers = []
    for r in rows:
        w = dict(r)
        total = w["annual_leave_total"] or 0
        used = w["annual_leave_used"] or 0
        w["remaining"] = max(0, total - used)
        w["pct"] = int(used / total * 100) if total else 0
        workers.append(w)

    return templates.TemplateResponse(
        request=request, name="client/leave_balance.html", context={
            "request": request,
            "page_title": "연차 현황",
            "user_name": user["user_name"],
            "workers": workers,
        }
    )


@router.post("/leave/balance/{employee_id}")
async def leave_balance_update(
    request: Request,
    employee_id: int,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
    annual_leave_total: int = Form(...),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    worker = conn.execute(
        "SELECT id, company_id FROM employees WHERE id=?", (employee_id,)
    ).fetchone()
    if worker and worker["company_id"] == company_id:
        conn.execute(
            "UPDATE employees SET annual_leave_total=? WHERE id=?",
            (annual_leave_total, employee_id),
        )
        conn.commit()

    return RedirectResponse(url="/client/leave/balance", status_code=303)


@router.get("/leave", response_class=HTMLResponse)
async def leave_list(
    request: Request,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    status_filter = request.query_params.get("status", "")
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 10

    company_id = get_company_id_for_client(conn, user["user_id"])
    if status_filter == "pending":
        all_leaves = get_pending_leaves(conn, company_id)
    else:
        all_leaves = get_all_leaves(conn, company_id, status_filter or None)
    pending_count = len(get_pending_leaves(conn, company_id))
    all_leaves = [dict(r) for r in all_leaves]
    for r in all_leaves:
        r["leave_type_label"] = LEAVE_TYPES.get(r["leave_type"], {}).get("label", r["leave_type"])
    company = conn.execute(
        "SELECT name FROM client_companies WHERE id=?", (company_id,)
    ).fetchone()
    company_name = company["name"] if company else ""

    total = len(all_leaves)
    total_pages = max(1, (total + per_page - 1) // per_page)
    leaves = all_leaves[(page - 1) * per_page: page * per_page]

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
            "total_count": total,
            "page": page,
            "total_pages": total_pages,
            "base_url": f"/client/leave?status={status_filter}&",
        }
    )


@router.get("/leave/{leave_id}", response_class=HTMLResponse)
async def leave_detail(
    request: Request,
    leave_id: int,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    row = conn.execute(
        """SELECT lr.*, e.name as emp_name, e.dept, e.employee_no, e.position,
                  e.annual_leave_total, e.annual_leave_used
           FROM leave_requests lr
           JOIN employees e ON lr.employee_id = e.id
           WHERE lr.id = ? AND e.company_id = ?""",
        (leave_id, company_id),
    ).fetchone()
    if not row:
        return RedirectResponse(url="/client/leave", status_code=303)
    leave = dict(row)
    lt = LEAVE_TYPES.get(leave["leave_type"], {})
    leave["leave_type_label"] = lt.get("label", leave["leave_type"])
    approval = get_approval(conn, 'leave', leave_id)
    approval = dict(approval) if approval else None
    if approval and approval.get("approver_id"):
        approver = conn.execute(
            "SELECT name FROM users WHERE id=?", (approval["approver_id"],)
        ).fetchone()
        approval["approver_name"] = approver["name"] if approver else ""

    return templates.TemplateResponse(
        request=request, name="client/leave_detail.html", context={
            "request": request,
            "page_title": f"{leave['emp_name']} 휴가 상세",
            "user_name": user["user_name"],
            "leave": leave,
            "approval": approval,
        }
    )


@router.post("/leave/{leave_id}/approve")
async def leave_approve(
    request: Request,
    leave_id: int,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    lr = conn.execute(
        "SELECT e.company_id FROM leave_requests lr JOIN employees e ON lr.employee_id=e.id WHERE lr.id=?",
        (leave_id,),
    ).fetchone()
    if lr and lr["company_id"] == company_id:
        approve_leave(conn, leave_id, user["user_id"])

    return RedirectResponse(url=f"/client/leave/{leave_id}", status_code=303)


@router.post("/leave/{leave_id}/reject")
async def leave_reject(
    request: Request,
    leave_id: int,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    form = await request.form()
    reason = form.get("reason", "")

    company_id = get_company_id_for_client(conn, user["user_id"])
    lr = conn.execute(
        "SELECT e.company_id FROM leave_requests lr JOIN employees e ON lr.employee_id=e.id WHERE lr.id=?",
        (leave_id,),
    ).fetchone()
    if lr and lr["company_id"] == company_id:
        reject_leave(conn, leave_id, user["user_id"], reason)

    return RedirectResponse(url=f"/client/leave/{leave_id}", status_code=303)


@router.get("/certificates", response_class=HTMLResponse)
async def cert_list(
    request: Request,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    rows = conn.execute(
        """SELECT cr.*, e.name as emp_name, e.dept, e.employee_no
           FROM certificate_requests cr
           JOIN employees e ON cr.employee_id = e.id
           WHERE e.company_id = ?
           ORDER BY cr.requested_at DESC""",
        (company_id,),
    ).fetchall()
    reqs = [dict(r) for r in rows]

    return templates.TemplateResponse(
        request=request, name="client/cert_list.html", context={
            "request": request,
            "page_title": "증명서 발급 현황",
            "user_name": user["user_name"],
            "requests": reqs,
            "total_count": len(reqs),
        }
    )


@router.get("/accommodation", response_class=HTMLResponse)
async def accommodation_list(
    request: Request,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    status_filter = request.query_params.get("status", "")

    company_id = get_company_id_for_client(conn, user["user_id"])
    sql = """SELECT ar.*, e.name as emp_name, e.dept, e.employee_no
             FROM accommodation_requests ar
             JOIN employees e ON ar.employee_id = e.id
             WHERE e.company_id = ?"""
    params = [company_id]
    if status_filter:
        sql += " AND ar.status = ?"
        params.append(status_filter)
    sql += " ORDER BY ar.created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    reqs = [dict(r) for r in rows]
    pending_count = conn.execute(
        """SELECT COUNT(*) FROM accommodation_requests ar
           JOIN employees e ON ar.employee_id = e.id
           WHERE e.company_id = ? AND ar.status = 'pending'""",
        (company_id,),
    ).fetchone()[0]

    return templates.TemplateResponse(
        request=request, name="client/accom_list.html", context={
            "request": request,
            "page_title": "편의지원 관리",
            "user_name": user["user_name"],
            "requests": reqs,
            "status_filter": status_filter,
            "pending_count": pending_count,
            "total_count": len(reqs),
            "category_labels": ACCOMMODATION_CATEGORY_LABELS,
            "status_labels": ACCOMMODATION_STATUS_LABELS,
            "urgency_labels": URGENCY_LABELS,
        }
    )


@router.get("/accommodation/{req_id}", response_class=HTMLResponse)
async def accommodation_detail(
    request: Request,
    req_id: int,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    row = conn.execute(
        """SELECT ar.*, e.name as emp_name, e.dept, e.employee_no, e.position
           FROM accommodation_requests ar
           JOIN employees e ON ar.employee_id = e.id
           WHERE ar.id = ? AND e.company_id = ?""",
        (req_id, company_id),
    ).fetchone()
    if not row:
        return RedirectResponse(url="/client/accommodation", status_code=303)
    req = dict(row)
    approval = get_approval(conn, 'accommodation', req_id)
    approval = dict(approval) if approval else None
    if approval and approval.get("approver_id"):
        approver = conn.execute(
            "SELECT name FROM users WHERE id=?", (approval["approver_id"],)
        ).fetchone()
        approval["approver_name"] = approver["name"] if approver else ""

    return templates.TemplateResponse(
        request=request, name="client/accom_detail.html", context={
            "request": request,
            "page_title": f"{req['emp_name']} 편의지원 상세",
            "user_name": user["user_name"],
            "req": req,
            "approval": approval,
            "category_labels": ACCOMMODATION_CATEGORY_LABELS,
            "status_labels": ACCOMMODATION_STATUS_LABELS,
            "urgency_labels": URGENCY_LABELS,
        }
    )


@router.post("/accommodation/{req_id}/approve")
async def accommodation_approve(
    request: Request,
    req_id: int,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    row = conn.execute(
        "SELECT e.company_id FROM accommodation_requests ar JOIN employees e ON ar.employee_id=e.id WHERE ar.id=?",
        (req_id,),
    ).fetchone()
    if row and row["company_id"] == company_id:
        approve(conn, "accommodation", req_id, user["user_id"])
        conn.execute(
            "UPDATE accommodation_requests SET status='approved' WHERE id=?",
            (req_id,),
        )
        conn.commit()

    return RedirectResponse(url="/client/accommodation", status_code=303)


@router.post("/accommodation/{req_id}/reject")
async def accommodation_reject(
    request: Request,
    req_id: int,
    user: dict = Depends(require_client_hr),
    conn=Depends(get_db),
):
    form = await request.form()
    reason = form.get("reason", "")

    company_id = get_company_id_for_client(conn, user["user_id"])
    row = conn.execute(
        "SELECT e.company_id FROM accommodation_requests ar JOIN employees e ON ar.employee_id=e.id WHERE ar.id=?",
        (req_id,),
    ).fetchone()
    if row and row["company_id"] == company_id:
        reject(conn, "accommodation", req_id, user["user_id"], reason)
        conn.execute(
            "UPDATE accommodation_requests SET status='rejected' WHERE id=?",
            (req_id,),
        )
        conn.commit()

    return RedirectResponse(url="/client/accommodation", status_code=303)


@router.get("/evaluations", response_class=HTMLResponse)
async def eval_list(
    request: Request,
    user: dict = Depends(require_client()),
    conn=Depends(get_db),
):
    year_filter = request.query_params.get("year", "")
    quarter_filter = request.query_params.get("quarter", "")

    company_id = get_company_id_for_client(conn, user["user_id"])
    sql = """SELECT we.*, e.name as emp_name, e.dept
             FROM worker_evaluations we
             JOIN employees e ON we.employee_id = e.id
             WHERE we.company_id = ?"""
    params = [company_id]
    if year_filter:
        sql += " AND we.eval_year = ?"
        params.append(int(year_filter))
    if quarter_filter:
        sql += " AND we.eval_quarter = ?"
        params.append(int(quarter_filter))
    sql += " ORDER BY we.eval_year DESC, we.eval_quarter DESC, e.name"
    rows = conn.execute(sql, params).fetchall()
    evals = [dict(r) for r in rows]

    year_rows = conn.execute(
        "SELECT DISTINCT eval_year FROM worker_evaluations WHERE company_id=? ORDER BY eval_year DESC",
        (company_id,),
    ).fetchall()
    years = [r["eval_year"] for r in year_rows]
    if not years:
        years = [now_kst().year]

    return templates.TemplateResponse(
        request=request, name="client/eval_list.html", context={
            "request": request,
            "page_title": "근로자 평가",
            "user_name": user["user_name"],
            "evals": evals,
            "years": years,
            "year_filter": year_filter,
            "quarter_filter": quarter_filter,
        }
    )


@router.get("/evaluations/new", response_class=HTMLResponse)
async def eval_new(
    request: Request,
    user: dict = Depends(require_client()),
    conn=Depends(get_db),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    workers = get_company_workers(conn, company_id) if company_id else []

    now = now_kst()
    current_quarter = (now.month - 1) // 3 + 1

    return templates.TemplateResponse(
        request=request, name="client/eval_form.html", context={
            "request": request,
            "page_title": "근로자 평가 등록",
            "user_name": user["user_name"],
            "workers": workers,
            "current_year": now.year,
            "current_quarter": current_quarter,
        }
    )


@router.post("/evaluations")
async def eval_create(
    request: Request,
    user: dict = Depends(require_client()),
    conn=Depends(get_db),
    employee_id: int = Form(...),
    eval_year: int = Form(...),
    eval_quarter: int = Form(...),
    work_quality: int = Form(3),
    work_attitude: int = Form(3),
    cooperation: int = Form(3),
    punctuality: int = Form(3),
    strengths: str = Form(""),
    improvements: str = Form(""),
    comments: str = Form(""),
):
    overall = (work_quality + work_attitude + cooperation + punctuality) / 4

    company_id = get_company_id_for_client(conn, user["user_id"])
    conn.execute("""
        INSERT OR REPLACE INTO worker_evaluations
            (employee_id, company_id, eval_year, eval_quarter,
             work_quality, work_attitude, cooperation, punctuality,
             overall_score, strengths, improvements, comments,
             evaluator_id, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))
    """, (
        employee_id, company_id, eval_year, eval_quarter,
        work_quality, work_attitude, cooperation, punctuality,
        overall, strengths, improvements, comments,
        user["user_id"],
    ))
    conn.commit()

    return RedirectResponse(url="/client/evaluations", status_code=303)


@router.get("/evaluations/{eval_id}", response_class=HTMLResponse)
async def eval_detail(
    request: Request,
    eval_id: int,
    user: dict = Depends(require_client()),
    conn=Depends(get_db),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    row = conn.execute(
        """SELECT we.*, e.name as emp_name, e.dept
           FROM worker_evaluations we
           JOIN employees e ON we.employee_id = e.id
           WHERE we.id = ? AND we.company_id = ?""",
        (eval_id, company_id),
    ).fetchone()
    if not row:
        return RedirectResponse(url="/client/evaluations", status_code=303)
    ev = dict(row)

    return templates.TemplateResponse(
        request=request, name="client/eval_detail.html", context={
            "request": request,
            "page_title": f"{ev['emp_name']} 평가 상세",
            "user_name": user["user_name"],
            "eval": ev,
        }
    )


@router.get("/contract", response_class=HTMLResponse)
async def contract(
    request: Request,
    user: dict = Depends(require_client()),
    conn=Depends(get_db),
):
    company_id = get_company_id_for_client(conn, user["user_id"])
    row = conn.execute(
        """SELECT name, business_no, contract_start, contract_end,
                  status, contact_name, contact_phone, contact_email
           FROM client_companies WHERE id=?""",
        (company_id,),
    ).fetchone()
    company = dict(row) if row else {}

    worker_count = conn.execute(
        "SELECT COUNT(*) FROM employees WHERE company_id=? AND status='active'",
        (company_id,),
    ).fetchone()[0]

    days_left = None
    if company.get("contract_end"):
        try:
            end = date.fromisoformat(company["contract_end"])
            days_left = (end - date.today()).days
        except ValueError:
            pass

    return templates.TemplateResponse(
        request=request, name="client/contract.html", context={
            "request": request,
            "page_title": "계약 관리",
            "user_name": user["user_name"],
            "company": company,
            "worker_count": worker_count,
            "days_left": days_left,
        }
    )
