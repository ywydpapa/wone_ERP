import json
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_staff, templates
from core.export import pdf_response
from core.notification import create_notification

router = APIRouter(prefix="/platform")

TASK_TYPE_LABELS = {
    "data_entry": "데이터 입력",
    "document_review": "자료 검토",
    "chat_support": "채팅 상담",
    "phone_support": "전화 상담",
    "approval": "결재/전자서명",
    "planning_drafting": "기획/문서 작성",
}

STATUS_LABELS = {
    "pending": "대기",
    "assigned": "배정됨",
    "in_progress": "진행 중",
    "review": "검토 중",
    "completed": "완료",
    "returned": "반려",
    "cancelled": "취소",
}

REQUEST_STATUS_LABELS = {
    "draft": "임시저장",
    "submitted": "제출됨",
    "review": "검토 중",
    "accepted": "수락",
    "rejected": "반려",
    "in_progress": "진행 중",
    "completed": "완료",
    "closed": "마감",
    "cancelled": "취소",
}

REQUEST_STATUS_CLASS = {
    "draft": "status-badge status-draft",
    "submitted": "status-badge status-pending",
    "review": "status-badge status-review",
    "accepted": "status-badge status-accepted",
    "in_progress": "status-badge status-in_progress",
    "completed": "status-badge status-completed",
    "rejected": "status-badge status-returned",
    "closed": "status-badge status-closed",
    "cancelled": "status-badge status-closed",
}

TASK_STATUS_CLASS = {
    "pending": "status-badge status-pending",
    "assigned": "status-badge status-progress",
    "in_progress": "status-badge status-in_progress",
    "review": "status-badge status-review",
    "completed": "status-badge status-completed",
    "returned": "status-badge status-returned",
    "cancelled": "status-badge status-cancelled",
}

PRIO_LABELS = {"urgent": "긴급", "high": "높음", "low": "낮음"}
PRIO_CLASS = {"urgent": "text-danger fw-600", "high": "", "low": "text-muted"}


@router.get("/monthly-report", response_class=HTMLResponse)
async def monthly_report_list(
    request: Request,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    reports = conn.execute(
        "SELECT mr.*, cc.name AS company_name, u.name AS creator_name "
        "FROM monthly_reports mr "
        "JOIN client_companies cc ON mr.company_id=cc.id "
        "LEFT JOIN users u ON mr.created_by=u.id "
        "ORDER BY mr.year DESC, mr.month DESC, cc.name"
    ).fetchall()

    companies = conn.execute(
        "SELECT id, name FROM client_companies WHERE status='active' ORDER BY name"
    ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="platform/monthly_report.html",
        context={
            "request": request,
            "page_title": "월간 리포트",
            "user_name": user["name"],
            "user_role": user["role"],
            "reports": [dict(r) for r in reports],
            "companies": [dict(c) for c in companies],
            "now_month": date.today().strftime("%Y-%m"),
        },
    )


def _build_report_data(conn, company_id, year, month):
    _, last_day = monthrange(year, month)
    month_start = f"{year}-{month:02d}-01"
    month_end = f"{year}-{month:02d}-{last_day}"

    employees = conn.execute(
        "SELECT id, name, dept, position, disability_type, disability_grade, "
        "hire_date, employment_insurance "
        "FROM employees WHERE company_id=? AND status='active'",
        (company_id,),
    ).fetchall()

    # 전월 재직자 수
    if month == 1:
        prev_y, prev_m = year - 1, 12
    else:
        prev_y, prev_m = year, month - 1
    _, prev_last = monthrange(prev_y, prev_m)
    prev_end = f"{prev_y}-{prev_m:02d}-{prev_last}"
    prev_count = conn.execute(
        "SELECT COUNT(*) FROM employees WHERE company_id=? AND status='active' "
        "AND hire_date <= ?", (company_id, prev_end)
    ).fetchone()[0]

    # 신규입사/퇴사
    new_hires = conn.execute(
        "SELECT name, hire_date FROM employees "
        "WHERE company_id=? AND hire_date BETWEEN ? AND ?",
        (company_id, month_start, month_end),
    ).fetchall()

    # 장애유형별 분포
    dtype_dist = {}
    for emp in employees:
        dt = emp["disability_type"] or "미등록"
        dtype_dist[dt] = dtype_dist.get(dt, 0) + 1

    workers = []
    total_work_days = 0
    total_tasks_done = 0
    possible_work_days = 0
    insurance_ok = 0

    for emp in employees:
        eid = emp["id"]

        att = conn.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN status='normal' THEN 1 ELSE 0 END) AS normal, "
            "  SUM(CASE WHEN status IN ('late','late_early') THEN 1 ELSE 0 END) AS late, "
            "  SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) AS absent, "
            "  SUM(CASE WHEN status IN ('early_leave','late_early') THEN 1 ELSE 0 END) AS early, "
            "  SUM(CASE WHEN status='late_early' THEN 1 ELSE 0 END) AS late_early, "
            "  SUM(CASE WHEN status='holiday' THEN 1 ELSE 0 END) AS holiday, "
            "  SUM(work_minutes) AS total_minutes "
            "FROM attendance WHERE employee_id=? AND work_date BETWEEN ? AND ?",
            (eid, month_start, month_end),
        ).fetchone()

        work_days = (att["normal"] or 0) + (att["late"] or 0) + (att["early"] or 0) - (att["late_early"] or 0)
        total_work_days += work_days
        possible_work_days += (att["total"] or 0)

        leave_days = conn.execute(
            "SELECT COALESCE(SUM(days), 0) AS d FROM leave_requests "
            "WHERE employee_id=? AND status='approved' "
            "AND start_date <= ? AND end_date >= ?",
            (eid, month_end, month_start),
        ).fetchone()["d"]

        task_stats = conn.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed, "
            "  SUM(CASE WHEN status IN ('assigned','in_progress') THEN 1 ELSE 0 END) AS active, "
            "  SUM(CASE WHEN status='returned' THEN 1 ELSE 0 END) AS returned "
            "FROM tasks WHERE assigned_to=? "
            "AND created_at BETWEEN ? AND ?",
            (eid, month_start, month_end + " 23:59:59"),
        ).fetchone()
        total_tasks_done += (task_stats["completed"] or 0)

        pay_row = conn.execute(
            "SELECT id, gross_pay, total_deduction, net_pay "
            "FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
            (eid, year, month),
        ).fetchone()
        pay = None
        if pay_row:
            base_amount = conn.execute(
                """SELECT COALESCE(SUM(pi.amount),0) FROM payslip_items pi
                   JOIN pay_items it ON it.id = pi.item_id
                   WHERE pi.payslip_id=? AND it.code='BASE'""",
                (pay_row["id"],),
            ).fetchone()[0]
            pay = dict(pay_row)
            pay["base_amount"] = base_amount
            pay["allowance_amount"] = pay_row["gross_pay"] - base_amount

        if emp.get("employment_insurance"):
            insurance_ok += 1

        workers.append({
            "id": eid,
            "name": emp["name"],
            "dept": emp["dept"],
            "position": emp["position"],
            "disability_type": emp["disability_type"],
            "disability_grade": emp["disability_grade"],
            "attendance": {
                "work_days": work_days,
                "late": att["late"] or 0,
                "absent": att["absent"] or 0,
                "early_leave": att["early"] or 0,
                "holiday": att["holiday"] or 0,
                "leave": leave_days,
                "total_minutes": att["total_minutes"] or 0,
            },
            "tasks": {
                "total": task_stats["total"] or 0,
                "completed": task_stats["completed"] or 0,
                "active": task_stats["active"] or 0,
                "returned": task_stats["returned"] or 0,
            },
            "payroll": dict(pay) if pay else None,
        })

    worker_count = len(workers)
    total_gross = sum(
        (w["payroll"]["gross_pay"] or 0) for w in workers if w["payroll"]
    )
    avg_work_days = round(total_work_days / worker_count, 1) if worker_count else 0
    att_rate = round(total_work_days / possible_work_days * 100, 1) if possible_work_days else 0
    paid_count = sum(1 for w in workers if w["payroll"])

    # 업무요청 집계
    task_type_stats = conn.execute(
        "SELECT wr.task_type, COUNT(*) AS cnt, "
        "SUM(CASE WHEN wr.status IN ('completed','closed') THEN 1 ELSE 0 END) AS done "
        "FROM work_requests wr WHERE wr.company_id=? "
        "AND wr.created_at BETWEEN ? AND ? GROUP BY wr.task_type",
        (company_id, month_start, month_end + " 23:59:59"),
    ).fetchall()

    # 상시근로자수
    company = conn.execute(
        "SELECT employee_count, representative FROM client_companies WHERE id=?",
        (company_id,)
    ).fetchone()
    total_emp = company["employee_count"] if company and company["employee_count"] else 0
    disability_ratio = round(worker_count / total_emp * 100, 1) if total_emp else 0

    return {
        "worker_count": worker_count,
        "prev_count": prev_count,
        "avg_work_days": avg_work_days,
        "att_rate": att_rate,
        "total_tasks_done": total_tasks_done,
        "total_gross": total_gross,
        "workers": workers,
        "workforce": {
            "current": worker_count,
            "prev_month": prev_count,
            "diff": worker_count - prev_count,
            "new_hires": [{"name": h["name"], "date": h["hire_date"]} for h in new_hires],
            "disability_distribution": dtype_dist,
        },
        "task_type_stats": [dict(r) for r in task_type_stats],
        "compliance": {
            "disability_ratio": disability_ratio,
            "total_employees": total_emp,
            "insurance_count": insurance_ok,
            "insurance_total": worker_count,
            "paid_count": paid_count,
        },
    }


@router.post("/monthly-report/generate")
async def monthly_report_generate(
    request: Request,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
    company_id: int = Form(...),
    target_month: str = Form(...),
):
    parts = target_month.split("-")
    year, month = int(parts[0]), int(parts[1])

    existing = conn.execute(
        "SELECT id FROM monthly_reports WHERE company_id=? AND year=? AND month=?",
        (company_id, year, month),
    ).fetchone()

    data = _build_report_data(conn, company_id, year, month)

    if existing:
        conn.execute(
            "UPDATE monthly_reports SET data=?, status='draft', "
            "created_by=?, created_at=datetime('now','localtime') "
            "WHERE id=?",
            (json.dumps(data, ensure_ascii=False), user["id"], existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO monthly_reports (company_id, year, month, data, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (company_id, year, month, json.dumps(data, ensure_ascii=False), user["id"]),
        )
    conn.commit()

    return RedirectResponse(url="/platform/monthly-report", status_code=303)


@router.get("/monthly-report/{report_id}", response_class=HTMLResponse)
async def monthly_report_detail(
    request: Request,
    report_id: int,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    report = conn.execute(
        "SELECT mr.*, cc.name AS company_name "
        "FROM monthly_reports mr "
        "JOIN client_companies cc ON mr.company_id=cc.id "
        "WHERE mr.id=?",
        (report_id,),
    ).fetchone()
    if not report:
        return RedirectResponse(url="/platform/monthly-report", status_code=303)

    data = json.loads(report["data"])

    return templates.TemplateResponse(
        request=request,
        name="platform/monthly_report_detail.html",
        context={
            "request": request,
            "page_title": f"{report['company_name']} - {report['year']}년 {report['month']}월 리포트",
            "user_name": user["name"],
            "user_role": user["role"],
            "report": dict(report),
            "data": data,
        },
    )


@router.get("/monthly-report/{report_id}/pdf")
async def monthly_report_pdf(
    request: Request,
    report_id: int,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    report = conn.execute(
        "SELECT mr.*, cc.name AS company_name "
        "FROM monthly_reports mr "
        "JOIN client_companies cc ON mr.company_id=cc.id "
        "WHERE mr.id=?",
        (report_id,),
    ).fetchone()
    if not report:
        return RedirectResponse(url="/platform/monthly-report", status_code=303)

    data = json.loads(report["data"])
    html = templates.get_template("report/monthly_report_pdf.html").render(
        report=dict(report), data=data,
        task_type_labels=TASK_TYPE_LABELS,
    )
    filename = f"report_{report['company_name']}_{report['year']}_{report['month']:02d}.pdf"
    return pdf_response(html, filename)


@router.post("/monthly-report/{report_id}/publish")
async def monthly_report_publish(
    request: Request,
    report_id: int,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    conn.execute(
        "UPDATE monthly_reports SET status='published' WHERE id=? AND status='draft'",
        (report_id,),
    )
    conn.commit()
    return RedirectResponse(url=f"/platform/monthly-report/{report_id}", status_code=303)


@router.post("/monthly-report/{report_id}/unpublish")
async def monthly_report_unpublish(
    request: Request,
    report_id: int,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    conn.execute(
        "UPDATE monthly_reports SET status='draft' WHERE id=? AND status='published'",
        (report_id,),
    )
    conn.commit()
    return RedirectResponse(url=f"/platform/monthly-report/{report_id}", status_code=303)


@router.get("/help-requests", response_class=HTMLResponse)
async def help_request_list(
    request: Request,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    status_filter = request.query_params.get("status", "")
    sql = (
        "SELECT h.*, e.name AS worker_name, t.title AS task_title, "
        "wr.title AS request_title, cc.name AS company_name "
        "FROM help_requests h "
        "JOIN employees e ON h.employee_id = e.id "
        "LEFT JOIN tasks t ON h.task_id = t.id "
        "LEFT JOIN work_requests wr ON h.work_request_id = wr.id "
        "LEFT JOIN client_companies cc ON wr.company_id = cc.id "
    )
    params = []
    if status_filter:
        sql += "WHERE h.status = ? "
        params.append(status_filter)
    sql += "ORDER BY h.created_at DESC"
    rows = conn.execute(sql, params).fetchall()

    return templates.TemplateResponse(
        request=request, name="platform/help_requests.html", context={
            "request": request,
            "page_title": "도움 요청 관리",
            "user_name": user["name"],
            "help_requests": [dict(r) for r in rows],
            "status_filter": status_filter,
        },
    )


@router.post("/help-requests/{help_id}/acknowledge")
async def help_acknowledge(
    request: Request, help_id: int,
    user: dict = Depends(require_staff), conn=Depends(get_db),
):
    conn.execute(
        "UPDATE help_requests SET status='acknowledged' WHERE id=? AND status='open'",
        (help_id,),
    )
    conn.commit()
    return RedirectResponse(url="/platform/help-requests", status_code=303)


@router.post("/help-requests/{help_id}/resolve")
async def help_resolve(
    request: Request, help_id: int,
    resolve_note: str = Form(""),
    user: dict = Depends(require_staff), conn=Depends(get_db),
):
    hr = conn.execute(
        "SELECT h.employee_id, h.task_id, t.title AS task_title "
        "FROM help_requests h LEFT JOIN tasks t ON h.task_id = t.id "
        "WHERE h.id=? AND h.status IN ('open','acknowledged')",
        (help_id,),
    ).fetchone()
    if not hr:
        return RedirectResponse(url="/platform/help-requests", status_code=303)
    conn.execute(
        "UPDATE help_requests SET status='resolved', resolved_by=?, resolve_note=?, "
        "resolved_at=datetime('now','localtime') WHERE id=?",
        (user["id"], resolve_note, help_id),
    )
    worker_uid = conn.execute(
        "SELECT user_id FROM employees WHERE id=?", (hr["employee_id"],)
    ).fetchone()
    if worker_uid:
        msg = f'도움 요청 해결: {hr["task_title"] or "업무"}'
        link = f'/task/{hr["task_id"]}' if hr["task_id"] else '/my-tasks'
        create_notification(conn, worker_uid["user_id"], msg, link=link)
    conn.commit()
    return RedirectResponse(url="/platform/help-requests", status_code=303)
