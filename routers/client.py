from datetime import date

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_client_with_company, templates
from routers.platform import TASK_TYPE_LABELS, STATUS_LABELS, REQUEST_STATUS_LABELS
from core.attendance import get_company_workers

router = APIRouter(prefix="/client")

PRIORITY_LABELS = {
    "low": "낮음",
    "normal": "보통",
    "high": "높음",
    "urgent": "긴급",
}

OUTPUT_FORMAT_LABELS = {
    "excel": "엑셀",
    "json": "JSON",
    "pdf": "PDF",
    "erp": "ERP 연동",
}


@router.get("/requests", response_class=HTMLResponse)
async def request_list(
    request: Request,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    status_filter = request.query_params.get("status", "")

    company_id = user["company_id"]
    sql = (
        "SELECT wr.*, e.name AS assigned_worker_name "
        "FROM work_requests wr "
        "LEFT JOIN employees e ON wr.assigned_to = e.id "
        "WHERE wr.company_id = ?"
    )
    params = [company_id]
    if status_filter:
        sql += " AND wr.status = ?"
        params.append(status_filter)
    sql += " ORDER BY wr.created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    reqs = [dict(r) for r in rows]
    total_count = conn.execute(
        "SELECT COUNT(*) FROM work_requests WHERE company_id = ?", (company_id,)
    ).fetchone()[0]

    return templates.TemplateResponse(
        request=request, name="client/request_list.html", context={
            "request": request,
            "page_title": "업무 요청 목록",
            "user_name": user["user_name"],
            "requests": reqs,
            "status_filter": status_filter,
            "total_count": total_count,
            "task_type_labels": TASK_TYPE_LABELS,
            "request_status_labels": REQUEST_STATUS_LABELS,
        }
    )


@router.get("/requests/new", response_class=HTMLResponse)
async def request_new(
    request: Request,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
    workers = get_company_workers(conn, company_id)

    return templates.TemplateResponse(
        request=request, name="client/request_form.html", context={
            "request": request,
            "page_title": "새 업무 요청",
            "user_name": user["user_name"],
            "task_type_labels": TASK_TYPE_LABELS,
            "priority_labels": PRIORITY_LABELS,
            "output_format_labels": OUTPUT_FORMAT_LABELS,
            "workers": workers,
        }
    )


@router.post("/requests")
async def request_create(
    request: Request,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
    title: str = Form(...),
    description: str = Form(""),
    task_type: str = Form(...),
    volume: int = Form(1),
    priority: str = Form("normal"),
    due_date: str = Form(""),
    assigned_to: str = Form(""),
    output_format: str = Form("excel"),
):
    emp_id = int(assigned_to) if assigned_to else None
    status = "assigned" if emp_id else "pending"

    company_id = user["company_id"]
    conn.execute(
        """INSERT INTO work_requests
           (company_id, requested_by, title, description, task_type, volume, priority, status,
            due_date, assigned_to, assigned_by, output_format)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (company_id, user["user_id"], title, description, task_type, volume, priority, status,
         due_date or None, emp_id, user["user_id"] if emp_id else None, output_format),
    )
    conn.commit()

    return RedirectResponse(url="/client/requests", status_code=303)


@router.get("/requests/{req_id}/edit", response_class=HTMLResponse)
async def request_edit(
    request: Request,
    req_id: int,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
    row = conn.execute(
        "SELECT * FROM work_requests WHERE id = ? AND company_id = ?",
        (req_id, company_id),
    ).fetchone()
    if not row or row["status"] not in ("pending", "assigned"):
        return RedirectResponse(url="/client/requests", status_code=303)
    work_req = dict(row)
    workers = get_company_workers(conn, company_id)

    return templates.TemplateResponse(
        request=request, name="client/request_edit.html", context={
            "request": request,
            "page_title": "요청 수정",
            "user_name": user["user_name"],
            "task_type_labels": TASK_TYPE_LABELS,
            "priority_labels": PRIORITY_LABELS,
            "output_format_labels": OUTPUT_FORMAT_LABELS,
            "workers": workers,
            "work_req": work_req,
        }
    )


@router.post("/requests/{req_id}/edit")
async def request_update(
    request: Request,
    req_id: int,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
    title: str = Form(...),
    description: str = Form(""),
    task_type: str = Form(...),
    volume: int = Form(1),
    priority: str = Form("normal"),
    due_date: str = Form(""),
    assigned_to: str = Form(""),
    output_format: str = Form("excel"),
):
    emp_id = int(assigned_to) if assigned_to else None
    status = "assigned" if emp_id else "pending"

    company_id = user["company_id"]
    row = conn.execute(
        "SELECT status FROM work_requests WHERE id = ? AND company_id = ?",
        (req_id, company_id),
    ).fetchone()
    if not row or row["status"] not in ("pending", "assigned"):
        return RedirectResponse(url="/client/requests", status_code=303)
    conn.execute(
        """UPDATE work_requests
           SET title=?, description=?, task_type=?, volume=?, priority=?, due_date=?,
               assigned_to=?, assigned_by=?, output_format=?, status=?,
               updated_at=datetime('now','localtime')
           WHERE id=?""",
        (title, description, task_type, volume, priority, due_date or None,
         emp_id, user["user_id"] if emp_id else None, output_format, status, req_id),
    )
    conn.commit()

    return RedirectResponse(url=f"/client/requests/{req_id}", status_code=303)


@router.post("/requests/{req_id}/cancel")
async def request_cancel(
    request: Request,
    req_id: int,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
    row = conn.execute(
        "SELECT status FROM work_requests WHERE id = ? AND company_id = ?",
        (req_id, company_id),
    ).fetchone()
    if row and row["status"] in ("pending", "assigned"):
        conn.execute(
            "UPDATE work_requests SET status='cancelled', updated_at=datetime('now','localtime') WHERE id=?",
            (req_id,),
        )
        conn.commit()

    return RedirectResponse(url="/client/requests", status_code=303)


@router.post("/requests/{req_id}/comments")
async def request_add_comment(
    request: Request,
    req_id: int,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
    content: str = Form(...),
):
    company_id = user["company_id"]
    row = conn.execute(
        "SELECT id FROM work_requests WHERE id = ? AND company_id = ?",
        (req_id, company_id),
    ).fetchone()
    if row:
        conn.execute(
            "INSERT INTO work_request_comments (request_id, user_id, author, content) VALUES (?, ?, ?, ?)",
            (req_id, user["user_id"], user["user_name"], content),
        )
        conn.commit()

    return RedirectResponse(url=f"/client/requests/{req_id}", status_code=303)


@router.get("/requests/{req_id}", response_class=HTMLResponse)
async def request_detail(
    request: Request,
    req_id: int,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
    work_req = conn.execute(
        """SELECT wr.*, cc.name as company_name
           FROM work_requests wr
           JOIN client_companies cc ON wr.company_id = cc.id
           WHERE wr.id = ? AND wr.company_id = ?""",
        (req_id, company_id),
    ).fetchone()
    if not work_req:
        return RedirectResponse(url="/", status_code=303)
    work_req = dict(work_req)
    tasks = conn.execute(
        """SELECT t.*, e.name as worker_name
           FROM tasks t
           LEFT JOIN employees e ON t.assigned_to = e.id
           WHERE t.work_request_id = ?
           ORDER BY t.id""",
        (req_id,),
    ).fetchall()
    tasks = [dict(t) for t in tasks]
    comments = conn.execute(
        "SELECT * FROM work_request_comments WHERE request_id = ? ORDER BY created_at",
        (req_id,),
    ).fetchall()
    comments = [dict(c) for c in comments]

    return templates.TemplateResponse(
        request=request, name="client/request_detail.html", context={
            "request": request,
            "page_title": work_req["title"],
            "user_name": user["user_name"],
            "work_req": work_req,
            "tasks": tasks,
            "comments": comments,
            "task_type_labels": TASK_TYPE_LABELS,
            "status_labels": STATUS_LABELS,
            "request_status_labels": REQUEST_STATUS_LABELS,
        }
    )


def _get_company_task(conn, task_id, company_id):
    return conn.execute(
        """SELECT t.*, wr.company_id, wr.title AS request_title, e.name AS worker_name
           FROM tasks t
           JOIN work_requests wr ON t.work_request_id = wr.id
           LEFT JOIN employees e ON t.assigned_to = e.id
           WHERE t.id = ? AND wr.company_id = ?""",
        (task_id, company_id),
    ).fetchone()


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def client_task_detail(
    request: Request,
    task_id: int,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    row = _get_company_task(conn, task_id, user["company_id"])
    if not row:
        return RedirectResponse(url="/client/requests", status_code=303)
    task = dict(row)

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

    return templates.TemplateResponse(
        request=request, name="client/task_detail.html", context={
            "request": request,
            "page_title": task["title"],
            "user_name": user["user_name"],
            "task": task,
            "deliverables": deliverable_list,
            "comments": [dict(c) for c in comments],
            "status_labels": STATUS_LABELS,
        }
    )


@router.post("/tasks/{task_id}/approve")
async def client_task_approve(
    request: Request,
    task_id: int,
    review_notes: str = Form(""),
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    row = _get_company_task(conn, task_id, user["company_id"])
    if not row or row["status"] != "review":
        return RedirectResponse(url="/client/requests", status_code=303)
    conn.execute(
        "UPDATE tasks SET status='completed', review_notes=?, completed_at=datetime('now','localtime'), "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (review_notes, task_id),
    )
    conn.commit()
    return RedirectResponse(url=f"/client/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/reject")
async def client_task_reject(
    request: Request,
    task_id: int,
    review_notes: str = Form(...),
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    row = _get_company_task(conn, task_id, user["company_id"])
    if not row or row["status"] != "review":
        return RedirectResponse(url="/client/requests", status_code=303)
    conn.execute(
        "UPDATE tasks SET status='returned', review_notes=?, "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (review_notes, task_id),
    )
    conn.commit()
    return RedirectResponse(url=f"/client/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/comments")
async def client_task_comment(
    request: Request,
    task_id: int,
    content: str = Form(...),
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    row = _get_company_task(conn, task_id, user["company_id"])
    if not row:
        return RedirectResponse(url="/client/requests", status_code=303)
    conn.execute(
        "INSERT INTO task_comments (task_id, user_id, author, content) VALUES (?,?,?,?)",
        (task_id, user["user_id"], user["user_name"], content),
    )
    conn.commit()
    return RedirectResponse(url=f"/client/tasks/{task_id}", status_code=303)


@router.get("/monthly-report", response_class=HTMLResponse)
async def monthly_report(
    request: Request,
    user: dict = Depends(require_client_with_company("hr")),
    conn=Depends(get_db),
):
    company = conn.execute(
        "SELECT name FROM client_companies WHERE id=?", (user["company_id"],)
    ).fetchone()

    return templates.TemplateResponse(
        request=request,
        name="client/monthly_report.html",
        context={
            "request": request,
            "page_title": "월간 리포트",
            "user_name": user["user_name"],
            "company_name": company["name"] if company else "",
            "now_month": date.today().strftime("%Y-%m"),
        },
    )
