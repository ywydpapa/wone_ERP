from core.tz import now_kst, today_kst

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_client_with_company, templates
from core.attendance import (
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


@router.get("/workers", response_class=HTMLResponse)
async def worker_list(
    request: Request,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    status_filter = request.query_params.get("status", "")
    search_query = request.query_params.get("q", "")

    company_id = user["company_id"]
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
    inactive_count = total_count - active_count

    month_start = today_kst().replace(day=1).isoformat()
    new_hire_count = sum(
        1 for w in workers
        if w.get("hire_date") and w["hire_date"] >= month_start
    )

    return templates.TemplateResponse(
        request=request, name="client/workers.html", context={
            "request": request,
            "page_title": "근로자 관리",
            "user_name": user["user_name"],
            "workers": workers,
            "total_count": total_count,
            "active_count": active_count,
            "inactive_count": inactive_count,
            "new_hire_count": new_hire_count,
            "status_filter": status_filter,
            "search_query": search_query,
            "disability_type_labels": DISABILITY_TYPE_LABELS,
        }
    )


@router.get("/workers/{employee_id}", response_class=HTMLResponse)
async def worker_detail(
    request: Request,
    employee_id: int,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
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
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    month = request.query_params.get("month", now_kst().strftime("%Y-%m"))
    status_filter = request.query_params.get("status", "")

    company_id = user["company_id"]
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
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    month = request.query_params.get("month", now_kst().strftime("%Y-%m"))
    company_id = user["company_id"]
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
