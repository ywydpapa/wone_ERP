from datetime import datetime, timedelta

from core.tz import today_kst, now_kst

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

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
        today = today_kst()
        today_str = today.isoformat()
        week_ago = (today - timedelta(days=7)).isoformat()

        new_requests = conn.execute(
            "SELECT COUNT(*) FROM work_requests WHERE status='submitted'"
        ).fetchone()[0]
        in_progress = conn.execute(
            "SELECT COUNT(*) FROM work_requests WHERE status='in_progress'"
        ).fetchone()[0]
        review_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='review'"
        ).fetchone()[0]
        week_completed = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='completed' AND completed_at>=?",
            (week_ago,)
        ).fetchone()[0]

        recent_requests = conn.execute(
            "SELECT wr.*, cc.name AS company_name "
            "FROM work_requests wr "
            "LEFT JOIN client_companies cc ON wr.company_id=cc.id "
            "ORDER BY wr.created_at DESC LIMIT 5"
        ).fetchall()

        overdue_requests = conn.execute(
            "SELECT wr.id, wr.title, wr.due_date, wr.status, cc.name AS company_name "
            "FROM work_requests wr "
            "LEFT JOIN client_companies cc ON wr.company_id=cc.id "
            "WHERE wr.due_date < ? AND wr.status NOT IN ('completed','closed','cancelled') "
            "ORDER BY wr.due_date",
            (today_str,)
        ).fetchall()

        today_att = conn.execute(
            "SELECT e.name, cc.name AS company_name, a.clock_in, a.clock_out, a.status "
            "FROM attendance a "
            "JOIN employees e ON a.employee_id=e.id "
            "LEFT JOIN client_companies cc ON e.company_id=cc.id "
            "WHERE a.work_date=? ORDER BY a.clock_in DESC",
            (today_str,),
        ).fetchall()
        att_total = conn.execute(
            "SELECT COUNT(*) FROM employees WHERE status='active'"
        ).fetchone()[0]

        return templates.TemplateResponse(
            request=request, name="platform/dashboard.html", context={
                "request": request,
                "page_title": "운영 현황",
                "user_name": user["name"],
                "new_requests": new_requests,
                "in_progress": in_progress,
                "review_tasks": review_tasks,
                "week_completed": week_completed,
                "recent_requests": recent_requests,
                "overdue_requests": overdue_requests,
                "today_att": today_att,
                "att_total": att_total,
                "att_clocked": len(today_att),
                "request_status_labels": REQUEST_STATUS_LABELS,
                "status_labels": STATUS_LABELS,
            }
        )

    elif role == "worker":
        today = today_kst().isoformat()
        now = now_kst()
        employee_id = get_employee_id(conn, user["id"])

        my_tasks = 0
        completed_today = 0
        today_attendance = None
        tasks_list = []
        unread_notif = 0

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
                ci = today_attendance.get('clock_in') or ''
                today_attendance['ci_short'] = ci[:5] if ci else '-'
                co = today_attendance.get('clock_out') or ''
                today_attendance['co_short'] = co[:5] if co else ''
                if ci and not co:
                    ci_dt = datetime.strptime(f"{today} {ci}", "%Y-%m-%d %H:%M:%S")
                    diff = now - ci_dt
                    today_attendance['elapsed_h'] = int(diff.total_seconds() // 3600)
                    today_attendance['elapsed_m'] = int((diff.total_seconds() % 3600) // 60)
            tasks_list = conn.execute(
                "SELECT * FROM tasks WHERE assigned_to=? AND status NOT IN ('completed','cancelled') "
                "ORDER BY priority DESC, due_date LIMIT 10",
                (employee_id,)
            ).fetchall()
            unread_notif = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                (user["id"],)
            ).fetchone()[0]

        weekdays = ['월', '화', '수', '목', '금', '토', '일']
        today_label = f"{now.month}월 {now.day}일 {weekdays[now.weekday()]}요일"

        return templates.TemplateResponse(
            request=request, name="worker/dashboard.html", context={
                "request": request,
                "page_title": "홈",
                "user_name": user["name"],
                "my_tasks": my_tasks,
                "completed_today": completed_today,
                "today_attendance": today_attendance,
                "tasks_list": tasks_list,
                "task_type_labels": TASK_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
                "today_label": today_label,
                "unread_notif": unread_notif,
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
                "SELECT COUNT(*) FROM work_requests WHERE company_id=? AND status IN ('submitted','review','accepted','in_progress')",
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


@router.get("/api/search")
async def global_search(
    request: Request,
    q: str = Query("", min_length=1),
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    role = user["role"]
    q = q.strip()
    if not q:
        return JSONResponse([])

    like = f"%{q}%"
    results = []

    if role == "platform_staff":
        for r in conn.execute(
            "SELECT id, name, employee_no FROM employees WHERE name LIKE ? OR employee_no LIKE ? LIMIT 5",
            (like, like),
        ).fetchall():
            results.append({"type": "employee", "label": f"{r['name']} ({r['employee_no']})", "url": f"/hr/employees/{r['id']}"})

        for r in conn.execute(
            "SELECT id, title FROM work_requests WHERE title LIKE ? OR id=? LIMIT 5",
            (like, q if q.isdigit() else -1),
        ).fetchall():
            results.append({"type": "work_request", "label": f"[업무요청] {r['title']}", "url": f"/platform/work-requests/{r['id']}"})

    elif role == "client":
        cu = conn.execute("SELECT company_id FROM client_users WHERE user_id=?", (user["id"],)).fetchone()
        cid = cu["company_id"] if cu else None
        if cid:
            for r in conn.execute(
                "SELECT id, name, employee_no FROM employees WHERE company_id=? AND (name LIKE ? OR employee_no LIKE ?) LIMIT 5",
                (cid, like, like),
            ).fetchall():
                results.append({"type": "employee", "label": f"{r['name']} ({r['employee_no']})", "url": f"/client/attendance/{r['id']}"})
            for r in conn.execute(
                "SELECT id, title FROM work_requests WHERE company_id=? AND title LIKE ? LIMIT 5",
                (cid, like),
            ).fetchall():
                results.append({"type": "work_request", "label": f"[업무요청] {r['title']}", "url": f"/client/requests/{r['id']}"})

    elif role == "worker":
        for r in conn.execute(
            "SELECT id, title, work_date FROM jobs WHERE user_id=? AND (title LIKE ? OR content LIKE ?) AND status != 'trash' ORDER BY id DESC LIMIT 5",
            (user["id"], like, like),
        ).fetchall():
            results.append({"type": "job", "label": f"[업무] {r['title']}", "url": f"/job_detail/{r['id']}"})

    if role != "client":
        for r in conn.execute(
            "SELECT id, doc_number, title FROM erp_docs WHERE slip_date IS NOT NULL AND (doc_number LIKE ? OR title LIKE ?) LIMIT 5",
            (like, like),
        ).fetchall():
            label = r["title"][:30] if r["title"] else ""
            results.append({"type": "slip", "label": f"[전표] {r['doc_number']} {label}", "url": f"/erp_doc/{r['id']}"})

        for r in conn.execute(
            "SELECT id, item_code, item_name FROM items WHERE item_code LIKE ? OR item_name LIKE ? LIMIT 5",
            (like, like),
        ).fetchall():
            results.append({"type": "item", "label": f"[품목] {r['item_code']} {r['item_name']}", "url": f"/items/{r['id']}/edit"})

        for r in conn.execute(
            "SELECT id, name, biz_no FROM partners WHERE name LIKE ? OR biz_no LIKE ? LIMIT 5",
            (like, like),
        ).fetchall():
            results.append({"type": "partner", "label": f"[거래처] {r['name']}", "url": f"/partners/{r['id']}/edit"})

        for r in conn.execute(
            "SELECT id, po_number FROM purchase_orders WHERE po_number LIKE ? LIMIT 3",
            (like,),
        ).fetchall():
            results.append({"type": "po", "label": f"[발주] {r['po_number']}", "url": f"/purchase-orders/{r['id']}"})

        for r in conn.execute(
            "SELECT id, so_number FROM sales_orders WHERE so_number LIKE ? LIMIT 3",
            (like,),
        ).fetchall():
            results.append({"type": "so", "label": f"[수주] {r['so_number']}", "url": f"/sales-orders/{r['id']}"})

    return JSONResponse(results[:15])
