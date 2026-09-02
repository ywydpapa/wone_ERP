import csv
import io
import calendar as cal_mod
from core.tz import today_kst
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse, Response
from core.db import with_status_meta
from core.deps import get_db, require_login, templates, get_employee_id
from routers.platform import TASK_TYPE_LABELS, STATUS_LABELS, REQUEST_STATUS_LABELS
from routers._helpers import check_job_owner

router = APIRouter()

# 업무일지

@router.get("/job_diary", response_class=HTMLResponse)
async def job_diary(
    request: Request,
    user: dict = Depends(require_login),
):
    return templates.TemplateResponse(
        request=request, name="worker/job_diary.html", context={
            "request": request, "page_title": "업무일지",
            "user_name": user["user_name"],
        }
    )


@router.get("/progress_jobs", response_class=HTMLResponse)
async def progress_jobs(
    request: Request,
    q: str = "",
    page: int = 1,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    per_page = 10
    base = "FROM jobs WHERE status NOT IN ('done','trash')"
    params = []
    if q:
        base += " AND title LIKE '%'||?||'%'"; params.append(q)
    total = conn.execute("SELECT COUNT(*) " + base, params).fetchone()[0]
    rows = with_status_meta(conn.execute(
        "SELECT * " + base + " ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 ELSE 2 END, id DESC LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page]
    ).fetchall())
    done_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0]
    return templates.TemplateResponse(
        request=request, name="worker/progress_jobs.html", context={
            "request": request, "page_title": "진행 중인 업무",
            "user_name": user["user_name"],
            "jobs": rows, "total": total, "done_count": done_count,
            "q": q, "page": page, "total_pages": max(1, (total + per_page - 1) // per_page),
        }
    )


@router.get("/completed_jobs", response_class=HTMLResponse)
async def completed_jobs(
    request: Request,
    q: str = "",
    page: int = 1,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["user_id"]
    per_page = 10
    count_params = [uid]
    count_sql = "SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='done'"
    params = [uid]
    sql = "SELECT * FROM jobs WHERE user_id=? AND status='done'"
    if q:
        sql += " AND title LIKE '%'||?||'%'"; params.append(q)
        count_sql += " AND title LIKE '%'||?||'%'"; count_params.append(q)
    total = conn.execute(count_sql, count_params).fetchone()[0]
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"; params += [per_page, (page - 1) * per_page]
    done_jobs = with_status_meta(conn.execute(sql, params).fetchall())
    progress_count = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE user_id=? AND status!='done'", (uid,)).fetchone()[0]
    return templates.TemplateResponse(
        request=request, name="worker/complete_job.html", context={
            "request": request, "page_title": "완료 업무",
            "user_name": user["user_name"],
            "done_jobs": done_jobs, "done_count": total, "progress_count": progress_count,
            "q": q, "page": page, "total_pages": max(1, (total + per_page - 1) // per_page),
        }
    )


@router.get("/task/{task_id}", response_class=HTMLResponse)
async def task_detail(
    request: Request,
    task_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["user_id"])
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

    return templates.TemplateResponse(
        request=request, name="worker/task_detail.html", context={
            "request": request,
            "page_title": task["title"],
            "user_name": user["user_name"],
            "task": task,
            "task_type_labels": TASK_TYPE_LABELS,
            "status_labels": STATUS_LABELS,
        }
    )


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
    job = with_status_meta([row])[0]
    return templates.TemplateResponse(
        request=request, name="worker/job_detail.html", context={
            "request": request, "page_title": "업무 상세",
            "job": job,
            "user_name": user["user_name"],
        }
    )


@router.get("/job/{job_id}/edit", response_class=HTMLResponse)
async def job_edit(
    request: Request,
    job_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["user_id"]
    denied = check_job_owner(conn, job_id, uid)
    if denied:
        return denied
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return HTMLResponse("<h2>업무를 찾을 수 없습니다</h2><a href='/emp_dash'>돌아가기</a>", status_code=404)
    return templates.TemplateResponse(
        request=request, name="worker/job_edit.html", context={
            "request": request, "page_title": "업무 수정",
            "job": dict(row),
            "user_name": user["user_name"],
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
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["user_id"]
    denied = check_job_owner(conn, job_id, uid)
    if denied:
        return denied
    conn.execute(
        "UPDATE jobs SET work_date=?, category=?, title=?, details=?, issues=?, status=?, dept=?, due_label=? WHERE id=?",
        (workDate, workCategory, workTitle, workDetails, workIssues, progressStatus, workDept, workDue, job_id),
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
    uid = user["user_id"]
    denied = check_job_owner(conn, job_id, uid)
    if denied:
        return denied
    conn.execute("UPDATE jobs SET status='trash' WHERE id=?", (job_id,))
    conn.commit()
    return RedirectResponse(url="/emp_dash", status_code=303)


@router.post("/api/jobs/{job_id}/restore")
async def restore_job(
    request: Request,
    job_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["user_id"]
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
    uid = user["user_id"]
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
    uid = user["user_id"]
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id=? AND status='trash' ORDER BY id DESC", (uid,)
    ).fetchall()
    return templates.TemplateResponse(
        request=request, name="worker/trash.html", context={
            "request": request, "page_title": "휴지통",
            "user_name": user["user_name"],
            "trashed_jobs": [dict(r) for r in rows],
        }
    )


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["user_id"]
    today = today_kst()
    year, month = today.year, today.month
    month_prefix = f"{year}-{month:02d}"
    rows = conn.execute(
        "SELECT id, work_date, title, status FROM jobs WHERE user_id=? AND work_date LIKE ?",
        (uid, f"{month_prefix}%")
    ).fetchall()
    events = [dict(r) for r in rows]
    events_by_date = {}
    for ev in events:
        events_by_date.setdefault(ev["work_date"], []).append(ev)
    weeks = cal_mod.monthcalendar(year, month)
    return templates.TemplateResponse(
        request=request, name="worker/calendar.html", context={
            "request": request, "page_title": "일정 관리",
            "user_name": user["user_name"],
            "weeks": weeks, "events": events, "events_by_date": events_by_date,
            "year": year, "month": month, "month_prefix": month_prefix,
            "today_str": today.isoformat(),
        }
    )


@router.post("/api/jobs")
async def create_job(
    request: Request,
    workDate: str = Form(""), workCategory: str = Form(""),
    workTitle: str = Form(""), workDetails: str = Form(""),
    workIssues: str = Form(""), progressStatus: str = Form("progress"),
    workDept: str = Form(""), workDue: str = Form(""),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = user["user_id"]
    conn.execute(
        "INSERT INTO jobs (user_id, work_date, category, title, details, issues, status, dept, due_label) VALUES (?,?,?,?,?,?,?,?,?)",
        (uid, workDate, workCategory, workTitle, workDetails, workIssues, progressStatus, workDept, workDue),
    )
    conn.commit()
    return RedirectResponse(url="/emp_dash", status_code=303)


@router.get("/api/jobs")
async def list_jobs(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


@router.post("/api/jobs/{job_id}/toggle")
async def toggle_job(
    request: Request,
    job_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    new_status = "progress" if row["status"] == "done" else "done"
    conn.execute("UPDATE jobs SET status=? WHERE id=?", (new_status, job_id))
    conn.commit()
    return {"status": new_status}


@router.get("/my-tasks", response_class=HTMLResponse)
async def my_tasks(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["user_id"])
    if not emp_id:
        return RedirectResponse(url="/", status_code=303)
    rows = conn.execute(
        """SELECT wr.*, e.name AS assigned_worker_name, cc.name AS company_name
           FROM work_requests wr
           LEFT JOIN employees e ON wr.assigned_to = e.id
           LEFT JOIN client_companies cc ON wr.company_id = cc.id
           WHERE wr.assigned_to = ?
           ORDER BY wr.created_at DESC""",
        (emp_id,),
    ).fetchall()
    reqs = [dict(r) for r in rows]

    return templates.TemplateResponse(
        request=request, name="worker/my_tasks.html", context={
            "request": request,
            "page_title": "내 업무 요청",
            "user_name": user["user_name"],
            "reqs": reqs,
            "task_type_labels": TASK_TYPE_LABELS,
            "request_status_labels": REQUEST_STATUS_LABELS,
        }
    )


@router.post("/my-tasks/{req_id}/start")
async def my_task_start(
    request: Request,
    req_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["user_id"])
    if not emp_id:
        return RedirectResponse(url="/", status_code=303)
    conn.execute(
        "UPDATE work_requests SET status='in_progress', updated_at=datetime('now','localtime') "
        "WHERE id=? AND assigned_to=? AND status IN ('assigned', 'pending')",
        (req_id, emp_id),
    )
    conn.commit()
    return RedirectResponse(url="/my-tasks", status_code=303)


@router.post("/my-tasks/{req_id}/complete")
async def my_task_complete(
    request: Request,
    req_id: int,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["user_id"])
    if not emp_id:
        return RedirectResponse(url="/", status_code=303)
    conn.execute(
        "UPDATE work_requests SET status='completed', updated_at=datetime('now','localtime') "
        "WHERE id=? AND assigned_to=? AND status='in_progress'",
        (req_id, emp_id),
    )
    conn.commit()
    return RedirectResponse(url="/my-tasks", status_code=303)


@router.get("/report_export")
async def report_export(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    rows = conn.execute(
        "SELECT id, title, dept, category, work_date, due_label, status, created_at FROM jobs WHERE status='done' ORDER BY id DESC"
    ).fetchall()
    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(["ID", "제목", "부서", "분류", "작업일", "기한", "상태", "등록일"])
    for r in rows:
        writer.writerow([r["id"], r["title"], r["dept"] or "", r["category"] or "", r["work_date"] or "", r["due_label"] or "", r["status"], r["created_at"] or ""])
    content = buf.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=\"completed_jobs.csv\""},
    )
