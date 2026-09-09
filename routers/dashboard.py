from core.tz import today_kst, now_kst

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from core.deps import get_db, require_login, templates, get_employee_id
from routers.platform import TASK_TYPE_LABELS, STATUS_LABELS, REQUEST_STATUS_LABELS

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    role = user["role"]

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
        today = today_kst().isoformat()
        today_att = conn.execute(
            "SELECT e.name, cc.name AS company_name, a.clock_in, a.clock_out, a.status "
            "FROM attendance a "
            "JOIN employees e ON a.employee_id=e.id "
            "LEFT JOIN client_companies cc ON e.company_id=cc.id "
            "WHERE a.work_date=? ORDER BY a.clock_in DESC",
            (today,),
        ).fetchall()
        att_total = conn.execute(
            "SELECT COUNT(*) FROM employees WHERE status='active'"
        ).fetchone()[0]
        att_clocked = len(today_att)

        return templates.TemplateResponse(
            request=request, name="platform/dashboard.html", context={
                "request": request,
                "page_title": "운영 현황",
                "user_name": user["name"],
                "worker_count": worker_count,
                "client_count": client_count,
                "pending_requests": pending_requests,
                "active_tasks": active_tasks,
                "recent_tasks": recent_tasks,
                "today_att": today_att,
                "att_total": att_total,
                "att_clocked": att_clocked,
                "task_type_labels": TASK_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
            }
        )

    elif role == "worker":
        today = today_kst().isoformat()
        employee_id = get_employee_id(conn, user["id"])

        my_tasks = 0
        completed_today = 0
        today_attendance = None
        tasks_list = []
        recent_att = []

        if employee_id:
            my_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status IN ('assigned','in_progress')",
                (employee_id,)
            ).fetchone()[0]
            completed_today = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status='completed' AND completed_at LIKE ?",
                (employee_id, today + "%")
            ).fetchone()[0]
            att_row = conn.execute(
                "SELECT * FROM attendance WHERE employee_id=? AND work_date=?",
                (employee_id, today)
            ).fetchone()
            if att_row:
                today_attendance = dict(att_row)
                today_attendance['clock_in_short'] = today_attendance['clock_in'][:5] if today_attendance.get('clock_in') else '-'
            else:
                today_attendance = att_row
            tasks_list = conn.execute(
                "SELECT * FROM tasks WHERE assigned_to=? AND status NOT IN ('completed','cancelled') "
                "ORDER BY priority DESC, due_date LIMIT 10",
                (employee_id,)
            ).fetchall()
            recent_att = conn.execute(
                "SELECT id, work_date, clock_in, clock_out, status, work_minutes, appeal "
                "FROM attendance WHERE employee_id=? ORDER BY work_date DESC LIMIT 5",
                (employee_id,)
            ).fetchall()

        return templates.TemplateResponse(
            request=request, name="worker/dashboard.html", context={
                "request": request,
                "page_title": "내 업무 현황",
                "user_name": user["name"],
                "my_tasks": my_tasks,
                "completed_today": completed_today,
                "today_attendance": today_attendance,
                "recent_att": recent_att,
                "tasks_list": tasks_list,
                "task_type_labels": TASK_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
            }
        )

    else:
        today = today_kst().isoformat()
        client_user = conn.execute(
            "SELECT company_id FROM client_users WHERE user_id = ?", (user["id"],)
        ).fetchone()
        company_id = client_user["company_id"] if client_user else None

        total_requests = 0
        active_requests = 0
        completed_tasks = 0
        recent_requests = []
        worker_count = 0
        today_attendance = 0
        pending_leave = 0
        pending_accom = 0
        total_worker_count = 0
        inactive_count = 0
        new_hire_count = 0
        today_att = []

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
            worker_count = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE company_id=? AND status='active'",
                (company_id,)
            ).fetchone()[0]
            today_attendance = conn.execute(
                "SELECT COUNT(*) FROM attendance a "
                "JOIN employees e ON a.employee_id=e.id "
                "WHERE e.company_id=? AND a.work_date=?",
                (company_id, today)
            ).fetchone()[0]
            pending_leave = conn.execute(
                "SELECT COUNT(*) FROM leave_requests lr "
                "JOIN employees e ON lr.employee_id=e.id "
                "WHERE e.company_id=? AND lr.status='pending'",
                (company_id,)
            ).fetchone()[0]
            pending_accom = conn.execute(
                "SELECT COUNT(*) FROM accommodation_requests ar "
                "JOIN employees e ON ar.employee_id=e.id "
                "WHERE e.company_id=? AND ar.status='pending'",
                (company_id,)
            ).fetchone()[0]
            total_worker_count = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE company_id=?",
                (company_id,)
            ).fetchone()[0]
            inactive_count = total_worker_count - worker_count
            month_start = today_kst().replace(day=1).isoformat()
            new_hire_count = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE company_id=? AND hire_date>=?",
                (company_id, month_start)
            ).fetchone()[0]
            today_att = conn.execute(
                "SELECT e.name, a.clock_in, a.clock_out, a.status "
                "FROM attendance a "
                "JOIN employees e ON a.employee_id=e.id "
                "WHERE e.company_id=? AND a.work_date=? ORDER BY a.clock_in DESC",
                (company_id, today),
            ).fetchall()

        return templates.TemplateResponse(
            request=request, name="client/dashboard.html", context={
                "request": request,
                "page_title": "고객사 현황",
                "user_name": user["name"],
                "total_requests": total_requests,
                "active_requests": active_requests,
                "completed_tasks": completed_tasks,
                "recent_requests": [dict(r) | {"created_date": r["created_at"][:10] if r["created_at"] else "-"} for r in recent_requests],
                "worker_count": total_worker_count,
                "today_attendance": today_attendance,
                "today_att": today_att,
                "pending_leave": pending_leave,
                "pending_accom": pending_accom,
                "active_worker_count": worker_count,
                "inactive_count": inactive_count,
                "new_hire_count": new_hire_count,
                "task_type_labels": TASK_TYPE_LABELS,
                "request_status_labels": REQUEST_STATUS_LABELS,
            }
        )
