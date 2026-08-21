from core.tz import today_kst

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.db import get_sqlite
from core.deps import check_login, get_current_user, templates
from routers.platform import TASK_TYPE_LABELS, STATUS_LABELS

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)

    user = get_current_user(request)
    role = user["user_role"]
    conn = get_sqlite()

    try:
        if role == "platform_staff":
            worker_count = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE status='active'"
            ).fetchone()[0]
            client_count = conn.execute(
                "SELECT COUNT(*) FROM client_companies WHERE status='active'"
            ).fetchone()[0]
            pending_requests = conn.execute(
                "SELECT COUNT(*) FROM work_requests WHERE status='pending'"
            ).fetchone()[0]
            active_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('assigned','in_progress')"
            ).fetchone()[0]
            recent_tasks = conn.execute(
                "SELECT t.*, e.name as worker_name, cc.name as worker_company "
                "FROM tasks t "
                "LEFT JOIN employees e ON t.assigned_to = e.id "
                "LEFT JOIN client_companies cc ON e.company_id = cc.id "
                "ORDER BY t.created_at DESC LIMIT 5"
            ).fetchall()

            return templates.TemplateResponse(
                request=request, name="platform/dashboard.html", context={
                    "request": request,
                    "page_title": "운영 현황",
                    "user_name": user["user_name"],
                    "worker_count": worker_count,
                    "client_count": client_count,
                    "pending_requests": pending_requests,
                    "active_tasks": active_tasks,
                    "recent_tasks": recent_tasks,
                    "task_type_labels": TASK_TYPE_LABELS,
                    "status_labels": STATUS_LABELS,
                }
            )

        elif role == "worker":
            today = today_kst().isoformat()
            employee = conn.execute(
                "SELECT id FROM employees WHERE user_id = ?", (user["user_id"],)
            ).fetchone()
            employee_id = employee["id"] if employee else None

            my_tasks = 0
            completed_today = 0
            today_attendance = None
            tasks_list = []

            if employee_id:
                my_tasks = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status IN ('assigned','in_progress')",
                    (employee_id,)
                ).fetchone()[0]
                completed_today = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status='completed' AND completed_at LIKE ?",
                    (employee_id, today + "%")
                ).fetchone()[0]
                today_attendance = conn.execute(
                    "SELECT * FROM attendance WHERE employee_id=? AND work_date=?",
                    (employee_id, today)
                ).fetchone()
                tasks_list = conn.execute(
                    "SELECT * FROM tasks WHERE assigned_to=? AND status NOT IN ('completed','cancelled') "
                    "ORDER BY priority DESC, due_date LIMIT 10",
                    (employee_id,)
                ).fetchall()

            return templates.TemplateResponse(
                request=request, name="worker/dashboard.html", context={
                    "request": request,
                    "page_title": "내 업무 현황",
                    "user_name": user["user_name"],
                    "my_tasks": my_tasks,
                    "completed_today": completed_today,
                    "today_attendance": today_attendance,
                    "tasks_list": tasks_list,
                }
            )

        else:  # client
            client_user = conn.execute(
                "SELECT company_id FROM client_users WHERE user_id = ?", (user["user_id"],)
            ).fetchone()
            company_id = client_user["company_id"] if client_user else None

            total_requests = 0
            active_requests = 0
            completed_tasks = 0
            recent_requests = []

            if company_id:
                total_requests = conn.execute(
                    "SELECT COUNT(*) FROM work_requests WHERE company_id=?",
                    (company_id,)
                ).fetchone()[0]
                active_requests = conn.execute(
                    "SELECT COUNT(*) FROM work_requests WHERE company_id=? AND status IN ('pending','accepted','in_progress')",
                    (company_id,)
                ).fetchone()[0]
                completed_tasks = conn.execute(
                    "SELECT COUNT(*) FROM tasks t "
                    "JOIN work_requests w ON t.work_request_id = w.id "
                    "WHERE w.company_id=? AND t.status='completed'",
                    (company_id,)
                ).fetchone()[0]
                recent_requests = conn.execute(
                    "SELECT * FROM work_requests WHERE company_id=? ORDER BY created_at DESC LIMIT 5",
                    (company_id,)
                ).fetchall()

            return templates.TemplateResponse(
                request=request, name="client/dashboard.html", context={
                    "request": request,
                    "page_title": "업무 요청 현황",
                    "user_name": user["user_name"],
                    "total_requests": total_requests,
                    "active_requests": active_requests,
                    "completed_tasks": completed_tasks,
                    "recent_requests": recent_requests,
                }
            )

    finally:
        conn.close()
