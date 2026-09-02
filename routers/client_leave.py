from core.tz import now_kst

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_client_hr_with_company, templates
from core.constants import ACCOMMODATION_CATEGORY_LABELS, ACCOMMODATION_STATUS_LABELS
from routers._helpers import get_page
from core.leave import (
    LEAVE_TYPES, get_pending_leaves, get_all_leaves,
    get_leave_balance, approve_leave, reject_leave,
    get_month_leaves, build_leave_calendar,
)
from core.approval import get_approval, approve, reject

router = APIRouter(prefix="/client")

URGENCY_LABELS = {
    "normal": "일반",
    "high": "높음",
    "urgent": "긴급",
}


@router.get("/leave/calendar", response_class=HTMLResponse)
async def leave_calendar(
    request: Request,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
        month = int(request.query_params.get("month", now.month))
    except ValueError:
        year, month = now.year, now.month

    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
    annual_leave_total: int = Form(...),
):
    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    status_filter = request.query_params.get("status", "")
    page = get_page(request)
    per_page = 10

    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    form = await request.form()
    reason = form.get("reason", "")

    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    status_filter = request.query_params.get("status", "")

    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
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
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    form = await request.form()
    reason = form.get("reason", "")

    company_id = user["company_id"]
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
