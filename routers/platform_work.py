from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_staff, templates
from core.notification import create_notification, get_notifications, mark_all_read, notify_all_staff
from core.workflow import log_activity, get_activity_logs, get_due_status
from routers.platform import (
    TASK_TYPE_LABELS, STATUS_LABELS, REQUEST_STATUS_LABELS,
    REQUEST_STATUS_CLASS, TASK_STATUS_CLASS, PRIO_LABELS, PRIO_CLASS,
)
from core.constants import ERP_MODULES, ERP_MODULE_LOG_MAP

router = APIRouter(prefix="/platform")



def _check_due_notification(conn, work_req, req_id):
    if work_req["status"] in ('completed', 'closed', 'cancelled'):
        return
    due = work_req["due_date"]
    if not due:
        return
    try:
        diff = (date.fromisoformat(due[:10]) - date.today()).days
    except ValueError:
        return
    if diff > 1:
        return

    already = conn.execute(
        "SELECT 1 FROM activity_logs WHERE target_type='work_request' AND target_id=? AND action='due_warning'",
        (req_id,)
    ).fetchone()
    if already:
        return

    label = "내일 마감" if diff == 1 else "마감 초과" if diff < 0 else "오늘 마감"
    title = work_req["title"]

    conn.execute(
        "INSERT INTO activity_logs (target_type, target_id, user_id, action, detail) "
        "VALUES ('work_request', ?, 0, 'due_warning', ?)",
        (req_id, f'{label}: {title}'),
    )

    task_workers = conn.execute(
        "SELECT DISTINCT e.user_id FROM tasks t "
        "JOIN employees e ON t.assigned_to=e.id "
        "WHERE t.work_request_id=? AND t.status NOT IN ('completed','cancelled')",
        (req_id,),
    ).fetchall()
    staff = conn.execute("SELECT id FROM users WHERE role='platform_staff'").fetchall()
    notified = set()
    for row in list(task_workers) + list(staff):
        uid = row["user_id"] if "user_id" in row.keys() else row["id"]
        if uid not in notified:
            create_notification(conn, uid, f'{label}: {title}', link=f'/platform/work-requests/{req_id}')
            notified.add(uid)



@router.get("/work-requests/dashboard", response_class=HTMLResponse)
async def work_request_dashboard(
    request: Request,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    counts = {}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM work_requests GROUP BY status"
    ).fetchall():
        counts[row["status"]] = row["cnt"]

    total = sum(counts.values())
    pending = counts.get("submitted", 0) + counts.get("review", 0)
    in_progress = counts.get("accepted", 0) + counts.get("in_progress", 0)
    completed = counts.get("completed", 0) + counts.get("closed", 0)

    avg_row = conn.execute(
        "SELECT AVG(julianday(completed_at) - julianday(submitted_at)) AS avg_days "
        "FROM work_requests WHERE completed_at IS NOT NULL AND submitted_at IS NOT NULL"
    ).fetchone()
    avg_days = round(avg_row["avg_days"], 1) if avg_row and avg_row["avg_days"] else 0

    due_row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN completed_at <= due_date OR completed_at IS NULL AND date('now') <= due_date THEN 1 ELSE 0 END) AS on_time "
        "FROM work_requests WHERE due_date IS NOT NULL AND status NOT IN ('draft','cancelled')"
    ).fetchone()
    if due_row and due_row["total"] > 0:
        compliance = round(due_row["on_time"] / due_row["total"] * 100)
    else:
        compliance = 0

    overdue = conn.execute(
        "SELECT wr.id, wr.title, wr.due_date, wr.status, cc.name AS company_name, "
        "julianday('now') - julianday(wr.due_date) AS overdue_days "
        "FROM work_requests wr JOIN client_companies cc ON wr.company_id=cc.id "
        "WHERE wr.due_date < date('now') AND wr.status NOT IN ('completed','closed','cancelled') "
        "ORDER BY wr.due_date LIMIT 10"
    ).fetchall()

    recent = conn.execute(
        "SELECT wr.id, wr.title, wr.completed_at, cc.name AS company_name "
        "FROM work_requests wr JOIN client_companies cc ON wr.company_id=cc.id "
        "WHERE wr.status IN ('completed','closed') ORDER BY wr.completed_at DESC LIMIT 5"
    ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="platform/work_dashboard.html",
        context={
            "request": request,
            "page_title": "업무요청 대시보드",
            "user_name": user["name"],
            "user_role": user["role"],
            "total": total,
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed,
            "avg_days": avg_days,
            "compliance": compliance,
            "overdue": [dict(r) for r in overdue],
            "recent": [dict(r) for r in recent],
            "request_status_labels": REQUEST_STATUS_LABELS,
        },
    )


@router.get("/work-requests/stats", response_class=HTMLResponse)
async def work_request_stats(
    request: Request,
    month: str = "",
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    today = date.today()
    if not month:
        month = today.strftime('%Y-%m')

    start = f"{month}-01"
    y, m = int(month[:4]), int(month[5:7])
    if m == 12:
        end = f"{y+1}-01-01"
    else:
        end = f"{y}-{m+1:02d}-01"

    status_counts = {}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM work_requests "
        "WHERE created_at >= ? AND created_at < ? GROUP BY status",
        (start, end),
    ).fetchall():
        status_counts[row["status"]] = row["cnt"]

    period_total = sum(status_counts.values())

    avg_row = conn.execute(
        "SELECT AVG(julianday(completed_at) - julianday(submitted_at)) AS avg_days "
        "FROM work_requests "
        "WHERE completed_at IS NOT NULL AND submitted_at IS NOT NULL "
        "AND completed_at >= ? AND completed_at < ?",
        (start, end),
    ).fetchone()
    avg_days = round(avg_row["avg_days"], 1) if avg_row and avg_row["avg_days"] else 0

    clients = conn.execute(
        "SELECT cc.name AS company_name, COUNT(*) AS cnt, "
        "SUM(CASE WHEN wr.status IN ('completed','closed') THEN 1 ELSE 0 END) AS done, "
        "AVG(CASE WHEN wr.completed_at IS NOT NULL AND wr.submitted_at IS NOT NULL "
        "THEN julianday(wr.completed_at) - julianday(wr.submitted_at) END) AS avg_d "
        "FROM work_requests wr JOIN client_companies cc ON wr.company_id=cc.id "
        "WHERE wr.created_at >= ? AND wr.created_at < ? "
        "GROUP BY cc.id ORDER BY cnt DESC",
        (start, end),
    ).fetchall()

    monthly = conn.execute(
        "SELECT strftime('%%Y-%%m', created_at) AS ym, COUNT(*) AS cnt, "
        "SUM(CASE WHEN status IN ('completed','closed') THEN 1 ELSE 0 END) AS done "
        "FROM work_requests WHERE created_at >= date(?, '-5 months') "
        "GROUP BY ym ORDER BY ym",
        (start,),
    ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="platform/work_stats.html",
        context={
            "request": request,
            "page_title": "업무요청 통계",
            "user_name": user["name"],
            "user_role": user["role"],
            "month": month,
            "period_total": period_total,
            "status_counts": status_counts,
            "completed_total": status_counts.get("completed", 0) + status_counts.get("closed", 0),
            "avg_days": avg_days,
            "clients": [dict(c) for c in clients],
            "monthly": [{**dict(m), "done_pct": round(m["done"] / m["cnt"] * 100) if m["cnt"] else 0} for m in monthly],
            "request_status_labels": REQUEST_STATUS_LABELS,
        },
    )


@router.get("/work-requests", response_class=HTMLResponse)
async def work_request_list(
    request: Request,
    status: str = "",
    q: str = "",
    page: int = 1,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    per_page = 20

    base_where = ""
    wheres = []
    params = []
    if status:
        wheres.append("wr.status=?")
        params.append(status)
    if q:
        wheres.append("(wr.title LIKE '%'||?||'%' OR cc.name LIKE '%'||?||'%')")
        params.extend([q, q])
    if wheres:
        base_where = "WHERE " + " AND ".join(wheres) + " "

    total = conn.execute(
        "SELECT COUNT(*) FROM work_requests wr "
        "JOIN client_companies cc ON wr.company_id=cc.id " + base_where, params
    ).fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page

    sql = (
        "SELECT wr.*, cc.name AS company_name, "
        "  (SELECT COUNT(*) FROM tasks t WHERE t.work_request_id=wr.id) AS task_total, "
        "  (SELECT COUNT(*) FROM tasks t WHERE t.work_request_id=wr.id AND t.status='completed') AS task_completed "
        "FROM work_requests wr "
        "JOIN client_companies cc ON wr.company_id=cc.id "
        + base_where +
        "ORDER BY wr.created_at DESC LIMIT ? OFFSET ?"
    )
    reqs = conn.execute(sql, params + [per_page, offset]).fetchall()

    today = date.today()

    def build_req(r):
        d = {**dict(r),
             "status_label": REQUEST_STATUS_LABELS.get(r["status"], r["status"]),
             "status_class": REQUEST_STATUS_CLASS.get(r["status"], ""),
             "due_status": get_due_status(r["due_date"]),
             "overdue_days": 0}
        if r["due_date"] and r["status"] not in ('completed', 'closed', 'cancelled'):
            try:
                diff = (today - date.fromisoformat(r["due_date"][:10])).days
                if diff > 0:
                    d["overdue_days"] = diff
            except ValueError:
                pass
        return d

    return templates.TemplateResponse(
        request=request,
        name="platform/work_request_list.html",
        context={
            "request": request,
            "page_title": "업무 요청 관리",
            "user_name": user["name"],
            "user_role": user["role"],
            "reqs": [build_req(r) for r in reqs],
            "selected_status": status,
            "q": q,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "task_type_labels": TASK_TYPE_LABELS,
            "request_status_labels": REQUEST_STATUS_LABELS,
        },
    )


def _task_with_erp_count(conn, t):
    d = {
        **dict(t),
        "status_label": STATUS_LABELS.get(t["status"], t["status"]),
        "status_class": TASK_STATUS_CLASS.get(t["status"], ""),
    }
    log_modules = ERP_MODULE_LOG_MAP.get(t["erp_module"] or "", [])
    if log_modules and t["assigned_to"]:
        uid = conn.execute(
            "SELECT user_id FROM employees WHERE id=?", (t["assigned_to"],)
        ).fetchone()
        if uid:
            since = t["started_at"] or t["created_at"] or ""
            ph = ",".join("?" * len(log_modules))
            d["erp_count"] = conn.execute(
                f"SELECT COUNT(*) FROM erp_activity_log WHERE user_id=? AND module IN ({ph}) AND created_at >= ?",
                (uid[0], *log_modules, since),
            ).fetchone()[0]
            return d
    d["erp_count"] = 0
    return d


@router.get("/work-requests/{req_id}", response_class=HTMLResponse)
async def work_request_detail(
    request: Request,
    req_id: int,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    work_req = conn.execute(
        "SELECT wr.*, cc.name AS company_name "
        "FROM work_requests wr JOIN client_companies cc ON wr.company_id=cc.id "
        "WHERE wr.id=?",
        (req_id,),
    ).fetchone()
    if not work_req:
        return RedirectResponse(url="/platform/work-requests", status_code=303)

    tasks = conn.execute(
        "SELECT t.*, e.name AS worker_name "
        "FROM tasks t LEFT JOIN employees e ON t.assigned_to=e.id "
        "WHERE t.work_request_id=? ORDER BY t.sort_order, t.created_at",
        (req_id,),
    ).fetchall()
    done_cnt = sum(1 for t in tasks if t["status"] == "completed")
    done_pct = int(done_cnt / len(tasks) * 100) if tasks else 0

    comments = conn.execute(
        "SELECT * FROM work_request_comments WHERE request_id=? ORDER BY created_at",
        (req_id,),
    ).fetchall()

    attachments_raw = conn.execute(
        "SELECT * FROM work_request_attachments WHERE request_id=? ORDER BY created_at",
        (req_id,),
    ).fetchall()
    attachments = []
    for a in attachments_raw:
        d = dict(a)
        fp = d.get("file_path", "")
        d["file_url"] = fp.split("|")[1] if "|" in fp else fp
        attachments.append(d)

    activities = get_activity_logs(conn, 'work_request', req_id)

    # D-1 알림 (조회 시점 체크, activity_log로 중복 방지)
    _check_due_notification(conn, work_req, req_id)

    return templates.TemplateResponse(
        request=request,
        name="platform/work_request_detail.html",
        context={
            "request": request,
            "page_title": f"{work_req['title']} - 요청 상세",
            "user_name": user["name"],
            "user_role": user["role"],
            "work_req": {
                **dict(work_req),
                "prio_label": PRIO_LABELS.get(work_req["priority"], "보통"),
                "prio_class": PRIO_CLASS.get(work_req["priority"], ""),
                "status_label": REQUEST_STATUS_LABELS.get(work_req["status"], work_req["status"]),
                "status_class": REQUEST_STATUS_CLASS.get(work_req["status"], ""),
            },
            "tasks": [_task_with_erp_count(conn, t) for t in tasks],
            "done_cnt": done_cnt,
            "done_pct": done_pct,
            "comments": [dict(c) for c in comments],
            "attachments": [dict(a) for a in attachments],
            "activities": [dict(a) for a in activities],
            "task_type_labels": TASK_TYPE_LABELS,
            "status_labels": STATUS_LABELS,
            "request_status_labels": REQUEST_STATUS_LABELS,
            "erp_modules": ERP_MODULES,
        },
    )



@router.post("/work-requests/{req_id}/comments")
async def work_request_comment(
    request: Request,
    req_id: int,
    content: str = Form(...),
    is_internal: int = Form(0),
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    conn.execute(
        "INSERT INTO work_request_comments (request_id, user_id, author, content, is_internal) VALUES (?,?,?,?,?)",
        (req_id, user["id"], user["name"], content, 1 if is_internal else 0),
    )
    log_activity(conn, 'work_request', req_id, user["id"], 'commented', content[:50])
    return RedirectResponse(url=f"/platform/work-requests/{req_id}", status_code=303)


@router.get("/notifications", response_class=HTMLResponse)
async def notification_list(
    request: Request,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    notifs = get_notifications(conn, user["id"], limit=50)
    mark_all_read(conn, user["id"])
    return templates.TemplateResponse(
        request=request,
        name="platform/notifications.html",
        context={
            "request": request,
            "page_title": "알림",
            "user_name": user["name"],
            "user_role": user["role"],
            "notifications": [dict(n) for n in notifs],
        },
    )
