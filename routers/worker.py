import csv
import io
import calendar as cal_mod
from datetime import datetime, timedelta
from core.tz import today_kst, now_kst
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse, Response
from core.db import with_status_meta
from core.deps import get_db, require_login, require_worker, templates, get_employee_id
from core.notification import get_notifications, mark_all_read, create_notification, notify_all_staff
from core.workflow import transition_task, log_activity, get_due_status, get_activity_logs
from routers.platform import TASK_TYPE_LABELS, STATUS_LABELS
from core.constants import ERP_MODULES, ERP_MODULE_LOG_MAP
from core.erp_task import get_erp_deliverables, sync_erp_volume
from core.export import esc_cell
from routers._helpers import check_job_owner, save_upload

router = APIRouter()

JOB_CATEGORIES = {
    "development": "개발/유지보수", "design": "디자인/기획",
    "support": "운영/고객지원", "meeting": "회의/미팅",
    "data_entry": "데이터 입력", "monitoring": "모니터링",
    "document": "문서 작성", "other": "기타 업무",
}

ERP_DOC_URLS = {
    "purchase": "/purchase-orders/{}",
    "sales": "/quotations/{}",
    "production": "/work-orders/{}",
    "master": "",
    "pr": "/purchase-requisitions/{}",
    "slip": "/erp_doc/{}",
}

@router.get("/job_diary", response_class=HTMLResponse)
async def job_diary(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    my_tasks = []
    if emp_id:
        rows = conn.execute(
            "SELECT id, title FROM tasks WHERE assigned_to=? AND status IN ('assigned','in_progress') ORDER BY created_at DESC",
            (emp_id,),
        ).fetchall()
        my_tasks = [dict(r) for r in rows]
    return templates.TemplateResponse(
        request=request, name="worker/job_diary.html", context={
            "request": request, "page_title": "업무일지",
            "user_name": user["name"],
            "my_tasks": my_tasks,
        }
    )


@router.get("/daily-report", response_class=HTMLResponse)
async def daily_report(
    request: Request,
    date: str = "",
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    if not date:
        date = today_kst().isoformat()

    dt = datetime.strptime(date, "%Y-%m-%d")
    prev_date = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (dt + timedelta(days=1)).strftime("%Y-%m-%d")

    uid = user["id"]
    is_staff = user["role"] == "platform_staff"
    worker_id = request.query_params.get("worker_id")

    if is_staff and worker_id:
        target_uid = int(worker_id)
        worker_info = conn.execute("SELECT name FROM users WHERE id=?", (target_uid,)).fetchone()
        worker_name = worker_info["name"] if worker_info else ""
    else:
        target_uid = uid
        worker_name = user["name"]

    # 수동 항목
    rows = conn.execute(
        """SELECT j.*, t.title AS task_title
           FROM jobs j LEFT JOIN tasks t ON j.task_id = t.id
           WHERE j.user_id=? AND j.work_date=? AND j.status != 'trash'
           ORDER BY j.start_time, j.id""",
        (target_uid, date),
    ).fetchall()
    manual_entries = []
    for r in rows:
        e = dict(r)
        e["entry_type"] = "manual"
        e["category_label"] = JOB_CATEGORIES.get(e.get("category", ""), e.get("category", ""))
        e["sort_time"] = e.get("start_time") or "99:99"
        manual_entries.append(e)

    # 자동 항목
    next_day = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    auto_rows = conn.execute(
        """SELECT id, action, module, target_id, doc_number, summary, created_at
           FROM erp_activity_log
           WHERE user_id=? AND created_at >= ? AND created_at < ?
           ORDER BY created_at""",
        (target_uid, date, next_day),
    ).fetchall()
    auto_entries = []
    for r in auto_rows:
        e = dict(r)
        e["entry_type"] = "auto"
        e["sort_time"] = e["created_at"][11:16] if len(e["created_at"]) >= 16 else "00:00"
        url_tpl = ERP_DOC_URLS.get(e["module"], "")
        e["doc_url"] = url_tpl.format(e["target_id"]) if url_tpl else ""
        auto_entries.append(e)

    entries = sorted(manual_entries + auto_entries, key=lambda x: x["sort_time"])

    total_minutes = sum(e.get("work_minutes") or 0 for e in manual_entries)
    total_volume = {}
    for e in manual_entries:
        if e.get("volume") and e.get("volume_unit"):
            total_volume[e["volume_unit"]] = total_volume.get(e["volume_unit"], 0) + e["volume"]

    done_count = sum(1 for e in manual_entries if e.get("status") == "done")
    has_manual = len(manual_entries) > 0
    has_pending_review = any(e.get("review_status") == "pending" for e in manual_entries)

    return templates.TemplateResponse(
        request=request, name="worker/daily_report.html", context={
            "request": request, "page_title": f"{date} 업무일지",
            "date": date, "prev_date": prev_date, "next_date": next_date,
            "entries": entries,
            "total_minutes": total_minutes, "total_volume": total_volume,
            "done_count": done_count, "entry_count": len(entries),
            "manual_count": len(manual_entries), "auto_count": len(auto_entries),
            "has_pending_review": has_pending_review, "has_manual": has_manual,
            "worker_name": worker_name, "is_staff": is_staff,
            "target_uid": target_uid, "own_uid": uid,
            "user_name": user["name"],
        }
    )


@router.post("/daily-report/quick-memo")
async def quick_memo(
    request: Request,
    date: str = Form(""),
    start_time: str = Form(""),
    title: str = Form(""),
    task_id: int = Form(0),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    if not title.strip():
        return RedirectResponse(url=f"/daily-report?date={date}", status_code=303)
    if not date:
        date = today_kst().isoformat()
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO jobs (user_id, work_date, category, title, status, start_time, task_id, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (user["id"], date, "etc", title.strip(), "done", start_time or None,
         task_id or None, now),
    )
    conn.commit()
    return RedirectResponse(url=f"/daily-report?date={date}", status_code=303)


@router.post("/daily-report/submit")
async def submit_daily_report(
    request: Request,
    date: str = Form(""),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    conn.execute(
        "UPDATE jobs SET review_status='pending' WHERE user_id=? AND work_date=? AND status != 'trash' AND review_status='none'",
        (user["id"], date),
    )
    conn.commit()
    notify_all_staff(
        conn,
        f"{user['name']}님이 {date} 업무일지 검토를 요청했습니다.",
        link=f"/daily-report?date={date}&worker_id={user['id']}",
    )
    return RedirectResponse(url=f"/daily-report?date={date}", status_code=303)


@router.get("/progress_jobs")
async def progress_jobs():
    return RedirectResponse("/my-tasks?status=in_progress", 302)


@router.get("/completed_jobs")
async def completed_jobs():
    return RedirectResponse("/my-tasks?status=completed", 302)


@router.get("/task/{task_id}", response_class=HTMLResponse)
async def task_detail(
    request: Request,
    task_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    if not emp_id:
        return RedirectResponse(url="/", status_code=303)
    row = conn.execute(
        """SELECT t.*, wr.title as request_title, wr.description as request_desc, wr.due_date as request_due
         FROM tasks t
         LEFT JOIN work_requests wr ON t.work_request_id = wr.id
         WHERE t.id = ? AND t.assigned_to = ?""",
        (task_id, emp_id),
    ).fetchone()
    if not row:
        return RedirectResponse(url="/", status_code=303)
    task = dict(row)

    erp_data = get_erp_deliverables(conn, task)
    if erp_data:
        sync_erp_volume(conn, task)
        conn.commit()
        task["completed_volume"] = erp_data["count"]

    deliverables = conn.execute(
        "SELECT * FROM task_deliverables WHERE task_id=? ORDER BY created_at DESC",
        (task_id,),
    ).fetchall()
    deliverable_list = []
    for d in deliverables:
        dd = dict(d)
        parts = dd["file_path"].split("|", 1)
        dd["stored_name"] = parts[1] if len(parts) == 2 else parts[0]
        deliverable_list.append(dd)

    comments = conn.execute(
        """SELECT tc.*, u.role as user_role
         FROM task_comments tc JOIN users u ON tc.user_id = u.id
         WHERE tc.task_id=? ORDER BY tc.created_at ASC""",
        (task_id,),
    ).fetchall()

    activities = get_activity_logs(conn, 'task', task_id)

    erp_logs = []
    erp_module = task.get("erp_module") or ""
    log_modules = ERP_MODULE_LOG_MAP.get(erp_module, [])
    if log_modules:
        assigned_at = task.get("started_at") or task.get("created_at") or ""
        placeholders = ",".join("?" * len(log_modules))
        erp_logs = [dict(r) for r in conn.execute(
            f"""SELECT id, action, module, target_id, doc_number, summary, created_at
                FROM erp_activity_log
                WHERE user_id=? AND module IN ({placeholders})
                  AND created_at >= ?
                ORDER BY created_at DESC""",
            (user["id"], *log_modules, assigned_at),
        ).fetchall()]

    return templates.TemplateResponse(
        request=request, name="worker/task_detail.html", context={
            "request": request,
            "page_title": task["title"],
            "user_name": user["name"],
            "task": task,
            "deliverables": deliverable_list,
            "comments": [dict(c) for c in comments],
            "task_type_labels": TASK_TYPE_LABELS,
            "status_labels": STATUS_LABELS,
            "activities": [dict(a) for a in activities],
            "due_status": get_due_status(task.get("due_date") or task.get("request_due")),
            "erp_modules": ERP_MODULES,
            "erp_logs": erp_logs,
            "erp_data": erp_data,
        }
    )


@router.get("/task/{task_id}/erp")
async def task_erp_entry(
    task_id: int,
    request: Request,
    user: dict = Depends(require_worker),
    conn=Depends(get_db),
):
    task = conn.execute(
        "SELECT * FROM tasks WHERE id = ? AND assigned_to = ?",
        (task_id, user["employee_id"])).fetchone()
    if not task or task["status"] in ("completed", "cancelled"):
        return RedirectResponse("/my-tasks", status_code=303)
    mod = ERP_MODULES.get(task["erp_module"] or "")
    if not mod or not mod.get("url"):
        return RedirectResponse(f"/task/{task_id}", status_code=303)
    request.session["erp_task_id"] = task_id
    return RedirectResponse(mod["url"], status_code=303)


def _get_task_for_worker(conn, task_id, emp_id):
    return conn.execute(
        "SELECT * FROM tasks WHERE id=? AND assigned_to=?", (task_id, emp_id)
    ).fetchone()


@router.post("/task/{task_id}/start")
async def task_start(
    request: Request, task_id: int,
    user: dict = Depends(require_login), conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    task = _get_task_for_worker(conn, task_id, emp_id)
    if not task or task["status"] != "assigned":
        return RedirectResponse(url="/my-tasks", status_code=303)
    transition_task(conn, task_id, 'start', user["id"], 'worker')
    return RedirectResponse(url=f"/task/{task_id}?msg=started", status_code=303)


@router.post("/task/{task_id}/submit")
async def task_submit(
    request: Request, task_id: int,
    completed_volume: int = Form(0),
    user: dict = Depends(require_login), conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    task = _get_task_for_worker(conn, task_id, emp_id)
    if not task or task["status"] != "in_progress":
        return RedirectResponse(url="/my-tasks", status_code=303)
    if completed_volume > 0:
        conn.execute(
            "UPDATE tasks SET completed_volume=? WHERE id=?",
            (completed_volume, task_id),
        )
    transition_task(conn, task_id, 'submit', user["id"], 'worker')
    return RedirectResponse(url=f"/task/{task_id}?msg=review", status_code=303)


@router.post("/task/{task_id}/resubmit")
async def task_resubmit(
    request: Request, task_id: int,
    user: dict = Depends(require_login), conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    task = _get_task_for_worker(conn, task_id, emp_id)
    if not task or task["status"] != "returned":
        return RedirectResponse(url="/my-tasks", status_code=303)
    transition_task(conn, task_id, 'resubmit', user["id"], 'worker')
    return RedirectResponse(url=f"/task/{task_id}?msg=resubmitted", status_code=303)


@router.post("/task/{task_id}/deliverables")
async def task_upload_deliverable(
    request: Request, task_id: int,
    comment: str = Form(""),
    file: UploadFile = File(None),
    user: dict = Depends(require_login), conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    task = _get_task_for_worker(conn, task_id, emp_id)
    if not task or task["status"] not in ("in_progress", "returned"):
        return RedirectResponse(url="/my-tasks", status_code=303)
    saved = await save_upload(file, upload_dir="var/uploads/deliverables")
    if isinstance(saved, JSONResponse):
        return saved
    if not saved:
        return RedirectResponse(url=f"/task/{task_id}", status_code=303)
    original_name = saved.split("|")[0] if "|" in saved else saved
    conn.execute(
        "INSERT INTO task_deliverables (task_id, user_id, file_name, file_path, comment) VALUES (?,?,?,?,?)",
        (task_id, user["id"], original_name, saved, comment),
    )
    conn.commit()
    log_activity(conn, 'task', task_id, user["id"], 'uploaded', original_name)
    return RedirectResponse(url=f"/task/{task_id}?msg=uploaded", status_code=303)


@router.post("/task/{task_id}/comments")
async def task_add_comment(
    request: Request, task_id: int,
    content: str = Form(...),
    user: dict = Depends(require_login), conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    task = _get_task_for_worker(conn, task_id, emp_id)
    if not task:
        return RedirectResponse(url="/my-tasks", status_code=303)
    conn.execute(
        "INSERT INTO task_comments (task_id, user_id, author, content) VALUES (?,?,?,?)",
        (task_id, user["id"], user["name"], content),
    )
    log_activity(conn, 'task', task_id, user["id"], 'commented', content[:50])
    mgr_ids = conn.execute(
        "SELECT cu.user_id FROM client_users cu "
        "JOIN work_requests wr ON wr.company_id = cu.company_id "
        "WHERE wr.id=?",
        (task["work_request_id"],),
    ).fetchall()
    for m in mgr_ids:
        create_notification(conn, m["user_id"], f'댓글: {content[:30]}', link=f'/client/tasks/{task_id}')
    conn.commit()
    return RedirectResponse(url=f"/task/{task_id}?msg=comment", status_code=303)


@router.post("/task/{task_id}/help")
async def task_help_request(
    request: Request, task_id: int,
    reason: str = Form(...),
    user: dict = Depends(require_login), conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    task = _get_task_for_worker(conn, task_id, emp_id)
    if not task:
        return RedirectResponse(url="/my-tasks", status_code=303)
    conn.execute(
        "INSERT INTO help_requests (task_id, work_request_id, employee_id, reason) VALUES (?,?,?,?)",
        (task_id, task["work_request_id"], emp_id, reason),
    )
    conn.commit()
    notify_all_staff(conn, f'도움 요청: {task["title"]}', link=f'/platform/help-requests')
    return RedirectResponse(url=f"/task/{task_id}?msg=help", status_code=303)


@router.get("/job/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return HTMLResponse("<h2>업무를 찾을 수 없습니다</h2><a href='/'>홈으로</a>", status_code=404)
    if row["user_id"] != user["id"] and user["role"] != "platform_staff":
        return HTMLResponse("<h2>접근 권한이 없습니다</h2><a href='/'>홈으로</a>", status_code=403)
    job = with_status_meta([row])[0]
    linked_task = None
    if job.get("task_id"):
        t = conn.execute("SELECT id, title FROM tasks WHERE id=?", (job["task_id"],)).fetchone()
        if t:
            linked_task = dict(t)
    return templates.TemplateResponse(
        request=request, name="worker/job_detail.html", context={
            "request": request, "page_title": "업무 상세",
            "job": job, "category_label": JOB_CATEGORIES.get(job.get("category", ""), job.get("category", "")),
            "linked_task": linked_task,
            "user_name": user["name"],
        }
    )


@router.get("/job/{job_id}/edit", response_class=HTMLResponse)
async def job_edit(
    request: Request,
    job_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["id"]
    denied = check_job_owner(conn, job_id, uid)
    if denied:
        return denied
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return HTMLResponse("<h2>업무를 찾을 수 없습니다</h2><a href='/'>돌아가기</a>", status_code=404)
    emp_id = get_employee_id(conn, uid)
    my_tasks = []
    if emp_id:
        t_rows = conn.execute(
            "SELECT id, title FROM tasks WHERE assigned_to=? AND status IN ('assigned','in_progress') ORDER BY created_at DESC",
            (emp_id,),
        ).fetchall()
        my_tasks = [dict(r) for r in t_rows]
    return templates.TemplateResponse(
        request=request, name="worker/job_edit.html", context={
            "request": request, "page_title": "업무 수정",
            "job": dict(row), "categories": list(JOB_CATEGORIES.items()),
            "my_tasks": my_tasks,
            "user_name": user["name"],
        }
    )


@router.post("/api/jobs/{job_id}")
async def update_job(
    request: Request,
    job_id: int,
    workDate: str = Form(""), workCategory: str = Form(""),
    workTitle: str = Form(""), workDetails: str = Form(""),
    workIssues: str = Form(""), progressStatus: str = Form("progress"),
    workDept: str = Form(""), workDue: str = Form(""),
    startTime: str = Form(""), endTime: str = Form(""),
    workVolume: int = Form(0), volumeUnit: str = Form(""),
    taskId: int = Form(0),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["id"]
    denied = check_job_owner(conn, job_id, uid)
    if denied:
        return denied
    work_minutes = 0
    if startTime and endTime:
        sh, sm = map(int, startTime.split(":"))
        eh, em = map(int, endTime.split(":"))
        diff = (eh * 60 + em) - (sh * 60 + sm)
        if diff > 0:
            work_minutes = diff
    conn.execute(
        """UPDATE jobs SET work_date=?, category=?, title=?, details=?, issues=?, status=?,
           dept=?, due_label=?, start_time=?, end_time=?, work_minutes=?, volume=?, volume_unit=?,
           task_id=? WHERE id=?""",
        (workDate, workCategory, workTitle, workDetails, workIssues, progressStatus,
         workDept, workDue, startTime, endTime, work_minutes, workVolume, volumeUnit,
         taskId or None, job_id),
    )
    conn.commit()
    return RedirectResponse(url=f"/job/{job_id}", status_code=303)


@router.post("/api/jobs/{job_id}/delete")
async def delete_job(
    request: Request,
    job_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["id"]
    denied = check_job_owner(conn, job_id, uid)
    if denied:
        return denied
    conn.execute("UPDATE jobs SET status='trash' WHERE id=?", (job_id,))
    conn.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/api/jobs/{job_id}/restore")
async def restore_job(
    request: Request,
    job_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["id"]
    denied = check_job_owner(conn, job_id, uid)
    if denied:
        return denied
    conn.execute("UPDATE jobs SET status='progress' WHERE id=? AND status='trash'", (job_id,))
    conn.commit()
    return RedirectResponse(url="/trash", status_code=303)


@router.post("/api/jobs/{job_id}/permanent_delete")
async def permanent_delete_job(
    request: Request,
    job_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["id"]
    denied = check_job_owner(conn, job_id, uid)
    if denied:
        return denied
    conn.execute("DELETE FROM jobs WHERE id=? AND status='trash'", (job_id,))
    conn.commit()
    return RedirectResponse(url="/trash", status_code=303)


@router.get("/trash", response_class=HTMLResponse)
async def trash_page(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id=? AND status='trash' ORDER BY id DESC", (user["id"],)
    ).fetchall()
    return templates.TemplateResponse(
        request=request, name="worker/trash.html", context={
            "request": request, "page_title": "휴지통",
            "user_name": user["name"],
            "trashed_jobs": [dict(r) for r in rows],
        }
    )


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(
    request: Request,
    y: int = 0, m: int = 0,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["id"]
    today = today_kst()
    year = y or today.year
    month = m or today.month
    if month < 1:
        year -= 1; month = 12
    elif month > 12:
        year += 1; month = 1
    month_prefix = f"{year}-{month:02d}"
    prev_y, prev_m = (year, month - 1) if month > 1 else (year - 1, 12)
    next_y, next_m = (year, month + 1) if month < 12 else (year + 1, 1)

    rows = conn.execute(
        "SELECT id, work_date, title, status FROM jobs WHERE user_id=? AND work_date LIKE ? AND status != 'trash'",
        (uid, f"{month_prefix}%")
    ).fetchall()
    events = [dict(r) for r in rows]
    events_by_date = {}
    count_by_date = {}
    for ev in events:
        events_by_date.setdefault(ev["work_date"], []).append(ev)
    for d, evs in events_by_date.items():
        count_by_date[d] = len(evs)
    weeks = cal_mod.monthcalendar(year, month)
    return templates.TemplateResponse(
        request=request, name="worker/calendar.html", context={
            "request": request, "page_title": "일정 관리",
            "user_name": user["name"],
            "weeks": weeks, "events": events, "events_by_date": events_by_date,
            "count_by_date": count_by_date,
            "year": year, "month": month, "month_prefix": month_prefix,
            "today_str": today.isoformat(),
            "prev_y": prev_y, "prev_m": prev_m,
            "next_y": next_y, "next_m": next_m,
        }
    )


@router.post("/api/jobs")
async def create_job(
    request: Request,
    workDate: str = Form(""), workCategory: str = Form(""),
    workTitle: str = Form(""), workDetails: str = Form(""),
    workIssues: str = Form(""), progressStatus: str = Form("progress"),
    workDept: str = Form(""), workDue: str = Form(""),
    startTime: str = Form(""), endTime: str = Form(""),
    workVolume: int = Form(0), volumeUnit: str = Form(""),
    taskId: int = Form(0),
    workAttachment: UploadFile = File(None),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["id"]
    work_minutes = 0
    if startTime and endTime:
        sh, sm = map(int, startTime.split(":"))
        eh, em = map(int, endTime.split(":"))
        diff = (eh * 60 + em) - (sh * 60 + sm)
        if diff > 0:
            work_minutes = diff

    attachment = ""
    if workAttachment and workAttachment.filename:
        result = await save_upload(workAttachment, "var/uploads/jobs")
        if isinstance(result, str):
            attachment = result

    conn.execute(
        """INSERT INTO jobs (user_id, work_date, category, title, details, issues, status,
           dept, due_label, start_time, end_time, work_minutes, volume, volume_unit, task_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (uid, workDate, workCategory, workTitle, workDetails, workIssues, progressStatus,
         workDept, workDue, startTime, endTime, work_minutes, workVolume, volumeUnit,
         taskId or None),
    )
    conn.commit()
    return RedirectResponse(url="/daily-report?date=" + workDate, status_code=303)


@router.get("/api/jobs")
async def list_jobs(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    if user["role"] == "platform_staff":
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/jobs/{job_id}/toggle")
async def toggle_job(
    request: Request,
    job_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["id"]
    denied = check_job_owner(conn, job_id, uid)
    if denied:
        return denied
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    new_status = "progress" if row["status"] == "done" else "done"
    conn.execute("UPDATE jobs SET status=? WHERE id=?", (new_status, job_id))
    conn.commit()
    return {"status": new_status}


@router.get("/my-tasks", response_class=HTMLResponse)
async def my_tasks(
    request: Request,
    status: str = "all",
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    if not emp_id:
        return RedirectResponse(url="/", status_code=303)
    today = today_kst().isoformat()
    status_filter = {"in_progress": "AND t.status='in_progress'",
                     "completed": "AND t.status='completed'",
                     "today": "AND t.status IN ('assigned','in_progress','returned') AND t.due_date <= ?"}.get(status, "")
    params = (emp_id, today) if status == "today" else (emp_id,)
    task_rows = conn.execute(
        f"""SELECT t.*, cc.name AS company_name, wr.title AS request_title
           FROM tasks t
           LEFT JOIN work_requests wr ON t.work_request_id = wr.id
           LEFT JOIN client_companies cc ON wr.company_id = cc.id
           WHERE t.assigned_to = ? AND t.status != 'cancelled'
           {status_filter}
           ORDER BY t.created_at DESC""",
        params,
    ).fetchall()
    tasks = []
    for r in task_rows:
        t = {**dict(r), "due_status": get_due_status(r["due_date"])}
        log_modules = ERP_MODULE_LOG_MAP.get(t.get("erp_module") or "", [])
        if log_modules:
            since = t.get("started_at") or t.get("created_at") or ""
            ph = ",".join("?" * len(log_modules))
            t["erp_count"] = conn.execute(
                f"SELECT COUNT(*) FROM erp_activity_log WHERE user_id=? AND module IN ({ph}) AND created_at >= ?",
                (user["id"], *log_modules, since),
            ).fetchone()[0]
        else:
            t["erp_count"] = 0
        tasks.append(t)

    assigned_count = sum(1 for t in tasks if t["status"] == "assigned")
    progress_count = sum(1 for t in tasks if t["status"] == "in_progress")
    completed_count = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status='completed'",
        (emp_id,)
    ).fetchone()[0]
    today_count = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status IN ('assigned','in_progress','returned') AND due_date <= ?",
        (emp_id, today)
    ).fetchone()[0]

    return templates.TemplateResponse(
        request=request, name="worker/my_tasks.html", context={
            "request": request,
            "page_title": "내 업무",
            "user_name": user["name"],
            "tasks": tasks,
            "assigned_count": assigned_count,
            "progress_count": progress_count,
            "completed_count": completed_count,
            "today_count": today_count,
            "status_labels": STATUS_LABELS,
            "erp_modules": ERP_MODULES,
            "cur_status": status,
        }
    )


@router.get("/report_export")
async def report_export(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    if user["role"] == "platform_staff":
        rows = conn.execute(
            "SELECT id, title, dept, category, work_date, due_label, status, created_at FROM jobs WHERE status='done' ORDER BY id DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title, dept, category, work_date, due_label, status, created_at FROM jobs WHERE user_id=? AND status='done' ORDER BY id DESC",
            (user["id"],)
        ).fetchall()
    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(["ID", "제목", "부서", "분류", "작업일", "기한", "상태", "등록일"])
    for r in rows:
        writer.writerow([esc_cell(v) for v in [r["id"], r["title"], r["dept"] or "", r["category"] or "", r["work_date"] or "", r["due_label"] or "", r["status"], r["created_at"] or ""]])
    content = buf.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=\"completed_jobs.csv\""},
    )


@router.get("/daily-report/summary", response_class=HTMLResponse)
async def daily_report_summary(
    request: Request,
    period: str = "week",
    base_date: str = "",
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    if not base_date:
        base_date = today_kst().isoformat()
    dt = datetime.strptime(base_date, "%Y-%m-%d")

    if period == "month":
        start = dt.replace(day=1)
        next_m = start.month + 1 if start.month < 12 else 1
        next_y = start.year if start.month < 12 else start.year + 1
        end = start.replace(year=next_y, month=next_m) - timedelta(days=1)
        prev_base = (start - timedelta(days=1)).replace(day=1).isoformat()
        next_base = (end + timedelta(days=1)).isoformat()
        label = f"{start.year}년 {start.month}월"
    else:
        weekday = dt.weekday()
        start = dt - timedelta(days=weekday)
        end = start + timedelta(days=6)
        prev_base = (start - timedelta(days=7)).isoformat()
        next_base = (start + timedelta(days=7)).isoformat()
        label = f"{start.strftime('%m/%d')} ~ {end.strftime('%m/%d')}"

    uid = user["id"]
    rows = conn.execute(
        """SELECT work_date, category, status, work_minutes, volume, volume_unit
           FROM jobs WHERE user_id=? AND work_date BETWEEN ? AND ? AND status != 'trash'
           ORDER BY work_date""",
        (uid, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
    ).fetchall()
    entries = [dict(r) for r in rows]

    total_minutes = sum(e.get("work_minutes") or 0 for e in entries)
    total_count = len(entries)
    done_count = sum(1 for e in entries if e.get("status") == "done")
    total_volume = {}
    for e in entries:
        if e.get("volume") and e.get("volume_unit"):
            total_volume[e["volume_unit"]] = total_volume.get(e["volume_unit"], 0) + e["volume"]

    by_category = {}
    for e in entries:
        cat = e.get("category") or "other"
        if cat not in by_category:
            by_category[cat] = {"count": 0, "minutes": 0}
        by_category[cat]["count"] += 1
        by_category[cat]["minutes"] += e.get("work_minutes") or 0
    cat_stats = [{"category": k, "label": JOB_CATEGORIES.get(k, k), **v} for k, v in by_category.items()]
    cat_stats.sort(key=lambda x: x["minutes"], reverse=True)

    by_date = {}
    for e in entries:
        d = e["work_date"]
        if d not in by_date:
            by_date[d] = {"count": 0, "minutes": 0, "done": 0}
        by_date[d]["count"] += 1
        by_date[d]["minutes"] += e.get("work_minutes") or 0
        if e.get("status") == "done":
            by_date[d]["done"] += 1
    date_stats = [{"date": k, **v} for k, v in sorted(by_date.items())]

    return templates.TemplateResponse(
        request=request, name="worker/diary_summary.html", context={
            "request": request, "page_title": "업무 요약",
            "user_name": user["name"],
            "period": period, "label": label,
            "base_date": base_date,
            "prev_base": prev_base, "next_base": next_base,
            "total_count": total_count, "done_count": done_count,
            "total_minutes": total_minutes, "total_volume": total_volume,
            "cat_stats": cat_stats, "date_stats": date_stats,
        }
    )


@router.get("/daily-report/export")
async def daily_report_export(
    request: Request,
    start: str = "", end: str = "",
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["id"]
    if not start:
        start = today_kst().replace(day=1).isoformat()
    if not end:
        end = today_kst().isoformat()
    rows = conn.execute(
        """SELECT j.work_date, j.start_time, j.end_time, j.work_minutes,
                  j.category, j.title, j.details, j.volume, j.volume_unit,
                  j.status, j.review_status, t.title AS task_title
           FROM jobs j LEFT JOIN tasks t ON j.task_id = t.id
           WHERE j.user_id=? AND j.work_date BETWEEN ? AND ? AND j.status != 'trash'
           ORDER BY j.work_date, j.start_time""",
        (uid, start, end),
    ).fetchall()
    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(["날짜", "시작", "종료", "소요(분)", "분류", "제목", "내용", "처리량", "단위", "상태", "검토", "연결업무"])
    for r in rows:
        writer.writerow([esc_cell(v) for v in [
            r["work_date"], r["start_time"] or "", r["end_time"] or "",
            r["work_minutes"] or 0,
            JOB_CATEGORIES.get(r["category"] or "", r["category"] or ""),
            r["title"], (r["details"] or "")[:200],
            r["volume"] or "", r["volume_unit"] or "",
            r["status"], r["review_status"] or "",
            r["task_title"] or "",
        ]])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="diary_{start}_{end}.csv"'},
    )


@router.get("/daily-report/review-list", response_class=HTMLResponse)
async def review_list(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    if user["role"] not in ("platform_staff", "client"):
        return RedirectResponse(url="/", status_code=303)
    if user["role"] == "client":
        cu = conn.execute(
            "SELECT company_id FROM client_users WHERE user_id=?", (user["id"],)
        ).fetchone()
        if not cu:
            return RedirectResponse(url="/", status_code=303)
        rows = conn.execute(
            """SELECT j.work_date, j.user_id, u.name AS worker_name,
               COUNT(*) AS entry_count,
               SUM(j.work_minutes) AS total_minutes,
               SUM(CASE WHEN j.status='done' THEN 1 ELSE 0 END) AS done_count
               FROM jobs j JOIN users u ON j.user_id = u.id
               JOIN employees e ON e.user_id = j.user_id
               WHERE j.review_status = 'pending' AND j.status != 'trash' AND e.company_id = ?
               GROUP BY j.work_date, j.user_id
               ORDER BY j.work_date DESC""",
            (cu["company_id"],),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT j.work_date, j.user_id, u.name AS worker_name,
               COUNT(*) AS entry_count,
               SUM(j.work_minutes) AS total_minutes,
               SUM(CASE WHEN j.status='done' THEN 1 ELSE 0 END) AS done_count
               FROM jobs j JOIN users u ON j.user_id = u.id
               WHERE j.review_status = 'pending' AND j.status != 'trash'
               GROUP BY j.work_date, j.user_id
               ORDER BY j.work_date DESC""",
        ).fetchall()

    reports = []
    for r in rows:
        d = dict(r)
        next_day_str = (datetime.strptime(d["work_date"], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        auto_cnt = conn.execute(
            "SELECT COUNT(*) FROM erp_activity_log WHERE user_id=? AND created_at >= ? AND created_at < ?",
            (d["user_id"], d["work_date"], next_day_str),
        ).fetchone()[0]
        d["auto_count"] = auto_cnt
        reports.append(d)

    return templates.TemplateResponse(
        request=request, name="worker/review_list.html", context={
            "request": request, "page_title": "업무일지 검토",
            "reports": reports,
            "user_name": user["name"],
        }
    )


@router.post("/daily-report/review")
async def review_daily_report(
    request: Request,
    worker_id: int = Form(0),
    date: str = Form(""),
    action: str = Form(""),
    comment: str = Form(""),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    if user["role"] not in ("platform_staff", "client"):
        return RedirectResponse(url="/", status_code=303)
    if user["role"] == "client":
        ok = conn.execute(
            "SELECT 1 FROM client_users cu JOIN employees e ON e.company_id = cu.company_id "
            "WHERE cu.user_id=? AND e.user_id=?",
            (user["id"], worker_id),
        ).fetchone()
        if not ok:
            return RedirectResponse(url="/daily-report/review-list", status_code=303)
    now = today_kst().isoformat()
    if action == "approve":
        conn.execute(
            """UPDATE jobs SET review_status='reviewed', reviewer_id=?, review_comment=?, reviewed_at=?
               WHERE user_id=? AND work_date=? AND review_status='pending'""",
            (user["id"], comment, now, worker_id, date),
        )
    elif action == "return":
        conn.execute(
            """UPDATE jobs SET review_status='returned', reviewer_id=?, review_comment=?, reviewed_at=?
               WHERE user_id=? AND work_date=? AND review_status='pending'""",
            (user["id"], comment, now, worker_id, date),
        )
    conn.commit()
    if action == "approve":
        create_notification(
            conn, worker_id,
            f"{date} 업무일지가 확인되었습니다.",
            link=f"/daily-report?date={date}",
        )
    elif action == "return":
        create_notification(
            conn, worker_id,
            f"{date} 업무일지에 보완 요청이 있습니다.",
            message=comment or "",
            link=f"/daily-report?date={date}",
        )
    return RedirectResponse(url="/daily-report/review-list", status_code=303)


@router.get("/notifications", response_class=HTMLResponse)
async def worker_notifications(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    notifs = get_notifications(conn, user["id"], limit=50)
    mark_all_read(conn, user["id"])
    return templates.TemplateResponse(
        request=request,
        name="worker/notifications.html",
        context={
            "request": request,
            "page_title": "알림",
            "user_name": user["name"],
            "notifications": [dict(n) for n in notifs],
        },
    )
