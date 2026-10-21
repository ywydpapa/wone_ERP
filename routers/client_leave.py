from datetime import date
from urllib.parse import quote

from core.tz import now_kst

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_client_hr_with_company, templates
from core.constants import ACCOMMODATION_CATEGORY_LABELS, ACCOMMODATION_STATUS_LABELS
from routers.mypage import _cert_context, _issue_cert
from routers._helpers import get_page
from core.leave import (
    LEAVE_TYPES, get_pending_leaves, get_all_leaves,
    cancel_leave, cancel_block,
    get_month_leaves, build_leave_calendar, get_leave_balance,
)
from core.leave_accrual import ensure_accrual
from core.approval import OPEN, act, doc_lines, my_line, reject_doc
from core.export import csv_response
from core.notification import create_notification
from core import audit

router = APIRouter(prefix="/client")

URGENCY_LABELS = {
    "normal": "일반",
    "high": "높음",
    "urgent": "긴급",
}


def _doc_line(conn, table, row_id, company_id, uid):
    row = conn.execute(
        f"SELECT r.doc_id FROM {table} r JOIN employees e ON e.id = r.employee_id WHERE r.id=? AND e.company_id=?",
        (row_id, company_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (row["doc_id"],)).fetchone()
    line = my_line(conn, doc, uid) if doc else None
    if not line:
        raise HTTPException(status_code=403)
    return doc, line


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
            "user_name": user["name"],
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
    year = int(request.query_params.get("year", date.today().year))
    company_id = user["company_id"]
    rows = conn.execute(
        "SELECT id, name, employee_no, dept, hire_date FROM employees WHERE company_id=? AND status='active' ORDER BY name",
        (company_id,),
    ).fetchall()
    workers = []
    for r in rows:
        w = dict(r)
        acc = ensure_accrual(conn, w["id"], year)
        w["granted"] = acc["granted"]
        w["used"] = acc["used"]
        w["remaining"] = max(0, round(acc["granted"] - acc["used"], 1))
        w["pct"] = int(acc["used"] / acc["granted"] * 100) if acc["granted"] else 0
        w["basis"] = acc["basis"]
        workers.append(w)

    return templates.TemplateResponse(
        request=request, name="client/leave_balance.html", context={
            "request": request,
            "page_title": "연차 현황",
            "user_name": user["name"],
            "workers": workers,
            "year": year,
        }
    )


@router.post("/leave/balance/{employee_id}")
async def leave_balance_update(
    request: Request,
    employee_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
    granted: int = Form(...),
    year: int = Form(...),
):
    company_id = user["company_id"]
    worker = conn.execute(
        "SELECT id, company_id FROM employees WHERE id=?", (employee_id,)
    ).fetchone()
    if worker and worker["company_id"] == company_id:
        ensure_accrual(conn, employee_id, year)
        conn.execute(
            """UPDATE leave_accruals SET granted=?, basis='manual'
               WHERE employee_id=? AND accrual_year=?""",
            (granted, employee_id, year),
        )
        conn.commit()

    return RedirectResponse(url=f"/client/leave/balance?year={year}", status_code=303)


LEAVE_SORTS = {"name": ("emp_name", ""), "dept": ("dept", ""), "type": ("leave_type", ""),
               "start": ("start_date", ""), "days": ("days", 0), "status": ("status", "")}
LEAVE_STATUS_LABEL = {"pending": "대기", "approved": "승인", "rejected": "반려", "cancelled": "취소"}


@router.get("/leave", response_class=HTMLResponse)
async def leave_list(
    request: Request,
    sort: str = "",
    dir: str = "",
    export: str = "",
    q: str = "",
    date_from: str = "",
    date_to: str = "",
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
        r["reject_short"] = (r.get("reject_reason") or "")[:20]

    if q:
        all_leaves = [r for r in all_leaves if q in r["emp_name"]]
    if date_from:
        all_leaves = [r for r in all_leaves if r["start_date"] >= date_from]
    if date_to:
        all_leaves = [r for r in all_leaves if r["start_date"] <= date_to]

    field_default = LEAVE_SORTS.get(sort)
    if field_default:
        field, default = field_default
        all_leaves.sort(key=lambda r: r[field] or default, reverse=dir == "desc")

    company = conn.execute(
        "SELECT name FROM client_companies WHERE id=?", (company_id,)
    ).fetchone()
    company_name = company["name"] if company else ""

    if export == "csv":
        data = [[r["employee_no"], r["emp_name"], r["dept"] or "-", r["leave_type_label"],
                 r["start_date"], r["end_date"], r["days"], r["reason"] or "-",
                 LEAVE_STATUS_LABEL.get(r["status"], r["status"])] for r in all_leaves]
        return csv_response(["사번", "성명", "부서", "유형", "시작일", "종료일", "일수", "사유", "상태"], data, "leaves.csv")

    total = len(all_leaves)
    total_pages = max(1, (total + per_page - 1) // per_page)
    leaves = all_leaves[(page - 1) * per_page: page * per_page]

    return templates.TemplateResponse(
        request=request, name="client/leave_list.html", context={
            "request": request,
            "page_title": "휴가 관리",
            "user_name": user["name"],
            "company_name": company_name,
            "leaves": leaves,
            "leave_types": LEAVE_TYPES,
            "status_filter": status_filter,
            "pending_count": pending_count,
            "total_count": total,
            "page": page,
            "total_pages": total_pages,
            "base_url": f"/client/leave?status={status_filter}&sort={sort}&dir={dir}&q={q}&date_from={date_from}&date_to={date_to}&",
            "sort": sort,
            "dir": dir,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
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
        """SELECT lr.*, e.name as emp_name, e.dept, e.employee_no, e.position
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
    bal = get_leave_balance(conn, leave["employee_id"], date.fromisoformat(leave["start_date"]).year)
    leave["leave_total"] = bal["total"]
    leave["leave_remaining"] = bal["remaining"]
    doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (leave["doc_id"],)).fetchone() if leave["doc_id"] else None
    cdoc = conn.execute("SELECT status FROM erp_docs WHERE id=?", (leave["cancel_doc_id"],)).fetchone() if leave["cancel_doc_id"] else None
    leave["cancel_pending"] = bool(cdoc and cdoc["status"] in OPEN)

    return templates.TemplateResponse(
        request=request, name="client/leave_detail.html", context={
            "request": request,
            "page_title": f"{leave['emp_name']} 휴가 상세",
            "user_name": user["name"],
            "leave": leave,
            "approval_lines": [l for l in doc_lines(conn, doc["id"]) if l["role"] != "참조"] if doc else [],
            "can_act": bool(doc and my_line(conn, doc, user["id"])),
            "error": request.query_params.get("error", ""),
        }
    )


@router.post("/leave/{leave_id}/approve")
async def leave_approve(
    request: Request,
    leave_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    doc, line = _doc_line(conn, "leave_requests", leave_id, user["company_id"], user["id"])
    act(conn, doc, line, user)
    conn.commit()
    return RedirectResponse(url=f"/client/leave/{leave_id}", status_code=303)


@router.post("/leave/{leave_id}/reject")
async def leave_reject(
    request: Request,
    leave_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    form = await request.form()
    doc, line = _doc_line(conn, "leave_requests", leave_id, user["company_id"], user["id"])
    reject_doc(conn, doc, line, user, form.get("reason", ""))
    conn.commit()
    return RedirectResponse(url=f"/client/leave/{leave_id}", status_code=303)


@router.post("/leave/{leave_id}/cancel")
async def leave_cancel(
    request: Request,
    leave_id: int,
    reason: str = Form(""),
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
    lr = conn.execute(
        "SELECT lr.*, e.company_id, e.name AS emp_name, e.user_id "
        "FROM leave_requests lr JOIN employees e ON lr.employee_id=e.id WHERE lr.id=?",
        (leave_id,),
    ).fetchone()
    if not lr or lr["company_id"] != company_id:
        raise HTTPException(status_code=404)
    reason = reason.strip()
    err = "취소 사유를 입력하세요." if not reason else cancel_block(conn, lr)
    if err:
        return RedirectResponse(url=f"/client/leave/{leave_id}?error={quote(err)}", status_code=303)
    if cancel_leave(conn, leave_id, reason):
        audit.log(conn, user["id"], "leave_cancel", "leave", leave_id,
                  f"{lr['emp_name']} {lr['start_date']}~{lr['end_date']}", detail={"reason": reason},
                  company_id=company_id)
        if lr["user_id"]:
            create_notification(conn, lr["user_id"], "휴가 취소", f"{lr['start_date']}~{lr['end_date']} 사유: {reason}",
                                "/mypage/leave")
        conn.commit()
    return RedirectResponse(url=f"/client/leave/{leave_id}", status_code=303)


CERT_SORTS = {"name": "e.name", "dept": "e.dept", "type": "cr.cert_type", "status": "cr.status"}


@router.get("/certificates", response_class=HTMLResponse)
async def cert_list(
    request: Request,
    sort: str = "",
    dir: str = "",
    export: str = "",
    status: str = "",
    q: str = "",
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
    order = CERT_SORTS.get(sort)
    order_sql = f"ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}" if order else "ORDER BY cr.requested_at DESC"
    sql = """SELECT cr.*, e.name as emp_name, e.dept, e.employee_no
             FROM certificate_requests cr
             JOIN employees e ON cr.employee_id = e.id
             WHERE e.company_id = ?"""
    params = [company_id]
    if status:
        sql += " AND cr.status = ?"
        params.append(status)
    if q:
        sql += " AND (e.name LIKE ? OR cr.cert_type LIKE ?)"
        params.append(f"%{q}%")
        params.append(f"%{q}%")
    rows = conn.execute(sql + " " + order_sql, params).fetchall()
    reqs = [dict(r) for r in rows]

    if export == "csv":
        data = [[r["employee_no"], r["emp_name"], r["dept"] or "-", r["cert_type"], r["purpose"] or "-",
                 "발급완료" if r["status"] == "completed" else "발급대기", r["cert_number"] or "-"] for r in reqs]
        return csv_response(["사번", "성명", "부서", "종류", "용도", "상태", "발급번호"], data, "certificates.csv")

    return templates.TemplateResponse(
        request=request, name="client/cert_list.html", context={
            "request": request,
            "page_title": "증명서 발급 현황",
            "user_name": user["name"],
            "requests": reqs,
            "total_count": len(reqs),
            "sort": sort,
            "dir": dir,
            "status_filter": status,
            "q": q,
        }
    )


@router.post("/certificates/{cert_id}/issue")
async def cert_issue(
    request: Request,
    cert_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    row = conn.execute(
        "SELECT e.company_id FROM certificate_requests cr JOIN employees e ON e.id=cr.employee_id WHERE cr.id=?",
        (cert_id,),
    ).fetchone()
    if not row or row["company_id"] != user["company_id"]:
        raise HTTPException(status_code=404)
    _issue_cert(conn, cert_id, user["id"])
    return RedirectResponse(url="/client/certificates", status_code=303)


@router.get("/certificates/{cert_id}/print", response_class=HTMLResponse)
async def cert_print(
    request: Request,
    cert_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    cert = _cert_context(conn, cert_id)
    if not cert or cert["company_id"] != user["company_id"] or cert["status"] != "completed":
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request, name="common/certificate_print.html", context={
            "request": request,
            "cert": cert,
        }
    )


ACCOM_SORTS = {"name": "e.name", "dept": "e.dept", "category": "ar.category",
               "urgency": "ar.urgency", "date": "ar.created_at", "status": "ar.status"}


@router.get("/accommodation", response_class=HTMLResponse)
async def accommodation_list(
    request: Request,
    sort: str = "",
    dir: str = "",
    export: str = "",
    q: str = "",
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
    if q:
        sql += " AND (e.name LIKE ? OR ar.title LIKE ?)"
        params.append(f"%{q}%")
        params.append(f"%{q}%")
    order = ACCOM_SORTS.get(sort)
    sql += f" ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}" if order else " ORDER BY ar.created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    reqs = [dict(r) for r in rows]

    if export == "csv":
        data = [[r["employee_no"], r["emp_name"], r["dept"] or "-",
                 ACCOMMODATION_CATEGORY_LABELS.get(r["category"], r["category"]), r["title"],
                 URGENCY_LABELS.get(r["urgency"], r["urgency"]), (r["created_at"] or "")[:10],
                 ACCOMMODATION_STATUS_LABELS.get(r["status"], r["status"])] for r in reqs]
        return csv_response(["사번", "성명", "부서", "유형", "제목", "긴급도", "신청일", "상태"], data, "accommodations.csv")

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
            "user_name": user["name"],
            "requests": reqs,
            "status_filter": status_filter,
            "pending_count": pending_count,
            "total_count": len(reqs),
            "category_labels": ACCOMMODATION_CATEGORY_LABELS,
            "status_labels": ACCOMMODATION_STATUS_LABELS,
            "urgency_labels": URGENCY_LABELS,
            "sort": sort,
            "dir": dir,
            "q": q,
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
    doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (req["doc_id"],)).fetchone() if req["doc_id"] else None

    return templates.TemplateResponse(
        request=request, name="client/accom_detail.html", context={
            "request": request,
            "page_title": f"{req['emp_name']} 편의지원 상세",
            "user_name": user["name"],
            "req": req,
            "approval_lines": [l for l in doc_lines(conn, doc["id"]) if l["role"] != "참조"] if doc else [],
            "can_act": bool(doc and my_line(conn, doc, user["id"])),
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
    doc, line = _doc_line(conn, "accommodation_requests", req_id, user["company_id"], user["id"])
    act(conn, doc, line, user)
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
    doc, line = _doc_line(conn, "accommodation_requests", req_id, user["company_id"], user["id"])
    reject_doc(conn, doc, line, user, form.get("reason", ""))
    conn.commit()
    return RedirectResponse(url="/client/accommodation", status_code=303)
