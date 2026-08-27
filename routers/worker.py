import json
import csv
import io
import calendar as cal_mod
from typing import Optional
from datetime import datetime
from core.tz import now_kst, today_kst
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.responses import JSONResponse, Response
from core.db import get_sqlite, with_status_meta
from core.deps import check_login, get_current_user, templates
from core.constants import ERP_DOC_TYPES, ERP_REDIRECTS, ERP_DOC_TYPE_LABELS, SIMPLE_SLIP_PURPOSES

router = APIRouter()


# 헬퍼

def _erp_docs_for(dtype: str):
    conn = get_sqlite()
    try:
        rows = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type=? ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 WHEN 'wait' THEN 2 ELSE 3 END, id DESC",
            (dtype,)
        ).fetchall())
    finally:
        conn.close()
    return rows


# 업무일지

@router.get("/job_diary", response_class=HTMLResponse)
async def job_diary(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request, name="worker/job_diary.html", context={
            "request": request, "page_title": "업무일지",
            "user_name": get_current_user(request)["user_name"],
        }
    )


@router.get("/progress_jobs", response_class=HTMLResponse)
async def progress_jobs(request: Request, q: str = "", page: int = 1):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    conn = get_sqlite()
    per_page = 10
    base = "FROM jobs WHERE status NOT IN ('done','trash')"
    params: list = []
    if q:
        base += " AND title LIKE '%'||?||'%'"; params.append(q)
    try:
        total = conn.execute("SELECT COUNT(*) " + base, params).fetchone()[0]
        rows = with_status_meta(conn.execute(
            "SELECT * " + base + " ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 ELSE 2 END, id DESC LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page]
        ).fetchall())
        done_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0]
    finally:
        conn.close()
    return templates.TemplateResponse(
        request=request, name="worker/progress_jobs.html", context={
            "request": request, "page_title": "진행 중인 업무",
            "user_name": u["user_name"],
            "jobs": rows, "total": total, "done_count": done_count,
            "q": q, "page": page, "total_pages": max(1, (total + per_page - 1) // per_page),
        }
    )


@router.get("/completed_jobs", response_class=HTMLResponse)
async def completed_jobs(request: Request, q: str = "", page: int = 1):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    uid = u["user_id"]
    conn = get_sqlite()
    per_page = 10
    count_params: list = [uid]
    count_sql = "SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='done'"
    params: list = [uid]
    sql = "SELECT * FROM jobs WHERE user_id=? AND status='done'"
    if q:
        sql += " AND title LIKE '%'||?||'%'"; params.append(q)
        count_sql += " AND title LIKE '%'||?||'%'"; count_params.append(q)
    try:
        total = conn.execute(count_sql, count_params).fetchone()[0]
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"; params += [per_page, (page - 1) * per_page]
        done_jobs = with_status_meta(conn.execute(sql, params).fetchall())
        progress_count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE user_id=? AND status!='done'", (uid,)).fetchone()[0]
    finally:
        conn.close()
    return templates.TemplateResponse(
        request=request, name="worker/complete_job.html", context={
            "request": request, "page_title": "완료 업무",
            "user_name": u["user_name"],
            "done_jobs": done_jobs, "done_count": total, "progress_count": progress_count,
            "q": q, "page": page, "total_pages": max(1, (total + per_page - 1) // per_page),
        }
    )


@router.get("/newarrived_jobs", response_class=HTMLResponse)
async def newarrived_jobs(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    uid = u["user_id"]
    conn = get_sqlite()
    try:
        unread_msgs = [dict(m) for m in conn.execute(
            "SELECT * FROM messages WHERE user_id=? AND direction='in' AND is_read=0 ORDER BY id DESC", (uid,)).fetchall()]
        read_msgs = [dict(m) for m in conn.execute(
            "SELECT * FROM messages WHERE user_id=? AND direction='in' AND is_read=1 ORDER BY id DESC", (uid,)).fetchall()]
        sent_msgs = [dict(m) for m in conn.execute(
            "SELECT * FROM messages WHERE user_id=? AND direction='out' ORDER BY id DESC", (uid,)).fetchall()]
    finally:
        conn.close()
    return templates.TemplateResponse(
        request=request, name="worker/new_arrived_job.html", context={
            "request": request, "page_title": "메시지함",
            "user_name": u["user_name"],
            "unread_msgs": unread_msgs, "read_msgs": read_msgs, "sent_msgs": sent_msgs,
            "unread_count": len(unread_msgs), "read_count": len(read_msgs),
        }
    )


@router.get("/job/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return HTMLResponse("<h2>업무를 찾을 수 없습니다</h2><a href='/'>홈으로</a>", status_code=404)
    job = with_status_meta([row])[0]
    return templates.TemplateResponse(
        request=request, name="worker/job_detail.html", context={
            "request": request, "page_title": "업무 상세",
            "job": job,
            "user_name": get_current_user(request)["user_name"],
        }
    )


@router.get("/job/{job_id}/edit", response_class=HTMLResponse)
async def job_edit(request: Request, job_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    uid = u["user_id"]
    conn = get_sqlite()
    try:
        owner = conn.execute("SELECT user_id FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not owner or owner["user_id"] != uid:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return HTMLResponse("<h2>업무를 찾을 수 없습니다</h2><a href='/emp_dash'>돌아가기</a>", status_code=404)
    return templates.TemplateResponse(
        request=request, name="worker/job_edit.html", context={
            "request": request, "page_title": "업무 수정",
            "job": dict(row),
            "user_name": u["user_name"],
        }
    )


@router.post("/api/jobs/{job_id}")
async def update_job(
    request: Request, job_id: int,
    workDate: str = Form(""), workCategory: str = Form(""),
    workTitle: str = Form(""), workDetails: str = Form(""),
    workIssues: str = Form(""), progressStatus: str = Form("progress"),
    workDept: str = Form(""), workDue: str = Form(""),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        owner = conn.execute("SELECT user_id FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not owner or owner["user_id"] != uid:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        conn.execute(
            "UPDATE jobs SET work_date=?, category=?, title=?, details=?, issues=?, status=?, dept=?, due_label=? WHERE id=?",
            (workDate, workCategory, workTitle, workDetails, workIssues, progressStatus, workDept, workDue, job_id),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url=f"/job/{job_id}", status_code=303)


@router.post("/api/jobs/{job_id}/delete")
async def delete_job(request: Request, job_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        owner = conn.execute("SELECT user_id FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not owner or owner["user_id"] != uid:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        conn.execute("UPDATE jobs SET status='trash' WHERE id=?", (job_id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/emp_dash", status_code=303)


@router.post("/api/jobs/{job_id}/restore")
async def restore_job(request: Request, job_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        owner = conn.execute("SELECT user_id FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not owner or owner["user_id"] != uid:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        conn.execute("UPDATE jobs SET status='progress' WHERE id=? AND status='trash'", (job_id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/trash", status_code=303)


@router.post("/api/jobs/{job_id}/permanent_delete")
async def permanent_delete_job(request: Request, job_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        owner = conn.execute("SELECT user_id FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not owner or owner["user_id"] != uid:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        conn.execute("DELETE FROM jobs WHERE id=? AND status='trash'", (job_id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/trash", status_code=303)


@router.get("/trash", response_class=HTMLResponse)
async def trash_page(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    uid = u["user_id"]
    conn = get_sqlite()
    try:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE user_id=? AND status='trash' ORDER BY id DESC", (uid,)
        ).fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse(
        request=request, name="worker/trash.html", context={
            "request": request, "page_title": "휴지통",
            "user_name": u["user_name"],
            "trashed_jobs": [dict(r) for r in rows],
        }
    )


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    uid = u["user_id"]
    today = today_kst()
    year, month = today.year, today.month
    month_prefix = f"{year}-{month:02d}"
    conn = get_sqlite()
    try:
        rows = conn.execute(
            "SELECT id, work_date, title, status FROM jobs WHERE user_id=? AND work_date LIKE ?",
            (uid, f"{month_prefix}%")
        ).fetchall()
    finally:
        conn.close()
    events = [dict(r) for r in rows]
    events_by_date: dict = {}
    for ev in events:
        events_by_date.setdefault(ev["work_date"], []).append(ev)
    weeks = cal_mod.monthcalendar(year, month)
    return templates.TemplateResponse(
        request=request, name="worker/calendar.html", context={
            "request": request, "page_title": "일정 관리",
            "user_name": u["user_name"],
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
    workAttachment: Optional[UploadFile] = File(None),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        conn.execute(
            "INSERT INTO jobs (user_id, work_date, category, title, details, issues, status, dept, due_label) VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, workDate, workCategory, workTitle, workDetails, workIssues, progressStatus, workDept, workDue),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/emp_dash", status_code=303)


@router.get("/api/jobs")
async def list_jobs(request: Request):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    conn = get_sqlite()
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@router.post("/api/jobs/{job_id}/toggle")
async def toggle_job(request: Request, job_id: int):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    conn = get_sqlite()
    try:
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        new_status = "progress" if row["status"] == "done" else "done"
        conn.execute("UPDATE jobs SET status=? WHERE id=?", (new_status, job_id))
        conn.commit()
    finally:
        conn.close()
    return {"status": new_status}


@router.get("/message/{msg_id}", response_class=HTMLResponse)
async def message_detail(request: Request, msg_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    uid = u["user_id"]
    conn = get_sqlite()
    try:
        row = conn.execute("SELECT * FROM messages WHERE id=? AND user_id=?", (msg_id, uid)).fetchone()
        if not row:
            return HTMLResponse("<h2>메시지를 찾을 수 없습니다</h2><a href='/newarrived_jobs'>돌아가기</a>", status_code=404)
        conn.execute("UPDATE messages SET is_read=1 WHERE id=?", (msg_id,))
        conn.commit()
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="worker/message_detail.html", context={
        "request": request, "page_title": "메시지 상세",
        "user_name": u["user_name"],
        "msg": dict(row),
    })


@router.post("/api/messages/{msg_id}/reply")
async def reply_message(request: Request, msg_id: int, body: str = Form(...)):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    uid = u["user_id"]
    conn = get_sqlite()
    try:
        row = conn.execute("SELECT sender FROM messages WHERE id=? AND user_id=?", (msg_id, uid)).fetchone()
        if row:
            recipient = row["sender"]
            conn.execute(
                "INSERT INTO messages (user_id, sender, recipient, body, time_label, is_read, direction) VALUES (?,?,?,?,datetime('now','localtime'),1,'out')",
                (uid, u["user_name"], recipient, body),
            )
            conn.execute("UPDATE messages SET is_read=1 WHERE id=?", (msg_id,))
            conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/newarrived_jobs", status_code=303)


@router.post("/api/messages/{msg_id}/read")
async def read_message(request: Request, msg_id: int):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    conn = get_sqlite()
    try:
        conn.execute("UPDATE messages SET is_read=1 WHERE id=?", (msg_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.get("/report_export")
async def report_export(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        rows = conn.execute(
            "SELECT id, title, dept, category, work_date, due_label, status, created_at FROM jobs WHERE status='done' ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()
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


@router.get("/api/dept/members")
async def dept_members(request: Request, dept: str):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    conn = get_sqlite()
    try:
        rows = conn.execute(
            "SELECT name, position FROM users WHERE dept=? ORDER BY id", (dept,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@router.get("/api/messages/thread")
async def message_thread(request: Request, with_name: str):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        rows = conn.execute(
            """SELECT sender, recipient, body, time_label, direction FROM messages
               WHERE user_id=? AND (
                   (direction='out' AND recipient=?) OR
                   (direction='in'  AND sender=?)
               )
               ORDER BY id DESC LIMIT 20""",
            (uid, with_name, with_name)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in reversed(rows)]


@router.post("/api/messages/send")
async def send_message(request: Request, to_name: str = Form(...), body: str = Form(...)):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    u = get_current_user(request)
    uid = u["user_id"]
    if not body.strip():
        return JSONResponse({"error": "내용을 입력해 주세요."}, status_code=400)
    conn = get_sqlite()
    try:
        recipient_row = conn.execute("SELECT id FROM users WHERE name=?", (to_name,)).fetchone()
        conn.execute(
            "INSERT INTO messages (user_id, sender, recipient, body, time_label, is_read, direction) VALUES (?,?,?,?,datetime('now','localtime'),1,'out')",
            (uid, u["user_name"], to_name, body.strip())
        )
        if recipient_row:
            conn.execute(
                "INSERT INTO messages (user_id, sender, recipient, body, time_label, is_read, direction) VALUES (?,?,?,?,datetime('now','localtime'),0,'in')",
                (recipient_row["id"], u["user_name"], to_name, body.strip())
            )
        conn.commit()
    finally:
        conn.close()
    return JSONResponse({"ok": True})


@router.post("/api/messages/read_all")
async def read_all_messages(request: Request):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        conn.execute("UPDATE messages SET is_read=1 WHERE user_id=?", (uid,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# ERP 대시보드 / 모듈 페이지

@router.get("/erp_dash", response_class=HTMLResponse)
async def erp_dash(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uname = get_current_user(request)["user_name"]
    uid = get_current_user(request)["user_id"]
    today = today_kst().isoformat()
    conn = get_sqlite()
    try:
        counts = {r["doc_type"]: r["cnt"] for r in [
            dict(r) for r in conn.execute(
                "SELECT doc_type, COUNT(*) AS cnt FROM erp_docs GROUP BY doc_type"
            ).fetchall()
        ]}
        recent = with_status_meta(conn.execute("SELECT * FROM erp_docs ORDER BY id DESC LIMIT 5").fetchall())
        today_jobs = with_status_meta(conn.execute(
            "SELECT * FROM jobs WHERE user_id=? AND work_date=? AND status != 'trash' ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 ELSE 2 END, id",
            (uid, today)
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(
        request=request, name="erp/erp_dash.html", context={
            "request": request, "page_title": "업무 대시보드",
            "doc_counts": counts, "recent_docs": recent,
            "user_name": uname,
            "today_jobs": today_jobs,
        }
    )


@router.get("/erp_hr", response_class=HTMLResponse)
async def erp_hr(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        leave_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='hr_task' AND title LIKE '%휴가%'"
        ).fetchone()[0]
        recruitment_count = 0
        docs = _erp_docs_for("hr_task")
        alerts = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='hr_task' AND status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/erp_hr.html", context={
        "request": request, "page_title": "인사관리 대시보드",
        "docs": docs,
        "alerts": alerts,
        "user_name": get_current_user(request)["user_name"],
        "user_count": user_count,
        "leave_count": leave_count,
        "recruitment_count": recruitment_count,
    })


@router.get("/erp_fa", response_class=HTMLResponse)
async def erp_fa(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='expense' ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 WHEN 'wait' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END, id DESC",
        ).fetchall())
        alert_rows = with_status_meta(conn.execute(
            """SELECT * FROM erp_docs
               WHERE doc_type IN ('expense', 'po')
               AND status IN ('urgent', 'wait', 'pending', 'progress')
               ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 WHEN 'wait' THEN 2 ELSE 3 END,
                        id DESC
               LIMIT 6""",
        ).fetchall())
        expense_done_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='expense' AND status IN ('done','approved')"
        ).fetchone()[0]
        expense_pending_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='expense' AND status IN ('wait','pending','urgent')"
        ).fetchone()[0]
        po_pending_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='po' AND status IN ('wait','pending','urgent','progress')"
        ).fetchone()[0]
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/erp_fa.html", context={
        "request": request, "page_title": "자금관리 대시보드",
        "docs": docs,
        "alerts": alert_rows,
        "expense_done_count": expense_done_count,
        "expense_pending_count": expense_pending_count,
        "po_pending_count": po_pending_count,
        "user_name": get_current_user(request)["user_name"],
    })


@router.get("/erp_scrm", response_class=HTMLResponse)
async def erp_scrm(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        activity_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='activity'"
        ).fetchone()[0]
        sales_leads_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='activity' AND status IN ('progress','wait')"
        ).fetchone()[0]
        voc_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='activity' AND status='urgent'"
        ).fetchone()[0]
        docs = _erp_docs_for("activity")
        alerts = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='activity' AND status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/erp_scrm.html", context={
        "request": request, "page_title": "영업/고객관리 대시보드",
        "docs": docs,
        "alerts": alerts,
        "user_name": get_current_user(request)["user_name"],
        "activity_count": activity_count,
        "sales_leads_count": sales_leads_count,
        "voc_count": voc_count,
    })


@router.get("/erp_purch", response_class=HTMLResponse)
async def erp_purch(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        po_total_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='po'"
        ).fetchone()[0]
        po_inprogress_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='po' AND status IN ('wait','pending','urgent','progress')"
        ).fetchone()[0]
        delayed_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='po' AND status='urgent'"
        ).fetchone()[0]
        docs = _erp_docs_for("po")
        alerts = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='po' AND status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/erp_purch.html", context={
        "request": request, "page_title": "구매관리 대시보드",
        "docs": docs,
        "alerts": alerts,
        "user_name": get_current_user(request)["user_name"],
        "po_total_count": po_total_count,
        "po_inprogress_count": po_inprogress_count,
        "delayed_count": delayed_count,
    })


@router.get("/erp_inventory", response_class=HTMLResponse)
async def erp_inventory(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        stock_move_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='stock_move'"
        ).fetchone()[0]
        outbound_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='stock_move'"
        ).fetchone()[0]
        low_stock_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='stock_move' AND status='urgent'"
        ).fetchone()[0]
        docs = _erp_docs_for("stock_move")
        alerts = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='stock_move' AND status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/erp_inventory.html", context={
        "request": request, "page_title": "재고관리 대시보드",
        "docs": docs,
        "alerts": alerts,
        "user_name": get_current_user(request)["user_name"],
        "stock_move_count": stock_move_count,
        "outbound_count": outbound_count,
        "low_stock_count": low_stock_count,
    })


@router.get("/erp_product", response_class=HTMLResponse)
async def erp_product(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        work_order_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='work_order'"
        ).fetchone()[0]
        production_inprogress_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='work_order' AND status IN ('progress','wait')"
        ).fetchone()[0]
        equipment_alert_count = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE doc_type='work_order' AND status='urgent'"
        ).fetchone()[0]
        docs = _erp_docs_for("work_order")
        alerts = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='work_order' AND status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/erp_product.html", context={
        "request": request, "page_title": "생산관리 대시보드",
        "docs": docs,
        "alerts": alerts,
        "user_name": get_current_user(request)["user_name"],
        "work_order_count": work_order_count,
        "production_inprogress_count": production_inprogress_count,
        "equipment_alert_count": equipment_alert_count,
    })


@router.get("/erp_groupware", response_class=HTMLResponse)
async def erp_groupware(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uname = get_current_user(request)["user_name"]
    uid = get_current_user(request)["user_id"]
    today = today_kst().isoformat()
    conn = get_sqlite()
    try:
        unread_mail = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id=? AND is_read=0 AND direction='in'", (uid,)
        ).fetchone()[0]
        today_jobs = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE user_id=? AND work_date=?", (uid, today)
        ).fetchone()[0]
        pending_docs = conn.execute(
            "SELECT COUNT(*) FROM erp_docs WHERE status IN ('wait','pending','urgent')"
        ).fetchone()[0]
        notices = [dict(r) for r in conn.execute(
            "SELECT id, category, title, author, dept, created_at FROM posts "
            "WHERE category IN ('notice', 'general') ORDER BY id DESC LIMIT 5"
        ).fetchall()]
        alerts = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/erp_groupware.html", context={
        "request": request, "page_title": "사내 그룹웨어",
        "docs": _erp_docs_for("draft"),
        "user_name": uname,
        "unread_mail": unread_mail,
        "today_jobs": today_jobs,
        "pending_docs": pending_docs,
        "notices": notices,
        "alerts": alerts,
    })


# ERP 문서 작성 폼 (동적 라우트)
for _route_name, (_dtype, _dlabel) in ERP_DOC_TYPES.items():
    def _make_handler(__dtype=_dtype, __dlabel=_dlabel):
        async def handler(request: Request):
            if not check_login(request):
                return RedirectResponse(url="/login", status_code=303)
            uid = get_current_user(request)["user_id"]
            conn = get_sqlite()
            try:
                try:
                    users = [dict(u) for u in conn.execute(
                        "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
                    ).fetchall()]
                except Exception:
                    users = [dict(u) for u in conn.execute(
                        "SELECT id, name, dept FROM users WHERE id != ? ORDER BY dept, name", (uid,)
                    ).fetchall()]
                try:
                    dt_row = conn.execute(
                        "SELECT form_schema FROM document_types WHERE name=?", (__dtype,)
                    ).fetchone()
                    form_schema = json.loads(dt_row["form_schema"]) if dt_row and dt_row["form_schema"] else {}
                except Exception:
                    form_schema = {}
            finally:
                conn.close()
            return templates.TemplateResponse(
                request=request, name="erp/erp_form.html", context={
                    "request": request, "page_title": __dlabel,
                    "doc_type": __dtype, "back_url": ERP_REDIRECTS[__dtype],
                    "user_name": get_current_user(request)["user_name"],
                    "users": users,
                    "form_schema": form_schema,
                }
            )
        return handler
    router.add_api_route(f"/{_route_name}", _make_handler(), methods=["GET"], response_class=HTMLResponse)


@router.get("/new_slip", response_class=HTMLResponse)
async def new_slip(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        users = [dict(u) for u in conn.execute(
            "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
        ).fetchall()]
    finally:
        conn.close()
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_form.html", context={
            "request": request, "page_title": "전표 입력",
            "user_name": get_current_user(request)["user_name"],
            "users": users,
        }
    )


@router.get("/new_slip_simple", response_class=HTMLResponse)
async def new_slip_simple(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        users = [dict(u) for u in conn.execute(
            "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
        ).fetchall()]
        recent_partners = [r[0] for r in conn.execute(
            "SELECT DISTINCT partner FROM slip_lines WHERE partner != '' ORDER BY id DESC LIMIT 20"
        ).fetchall()]
    finally:
        conn.close()
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_simple.html", context={
            "request": request, "page_title": "간편 전표 입력",
            "user_name": get_current_user(request)["user_name"],
            "users": users,
            "purposes": SIMPLE_SLIP_PURPOSES,
            "recent_partners": recent_partners,
        }
    )


@router.post("/api/slip/simple")
async def create_slip_simple(
    request: Request,
    direction: str = Form(...),
    slip_date: str = Form(""),
    amount: str = Form(""),
    partner: str = Form(""),
    purpose: str = Form(""),
    memo: str = Form(""),
    reviewer_id: int = Form(...),
    approver_id: int = Form(...),
    attachment: Optional[UploadFile] = File(None),
    save_mode: str = Form("submit"),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)

    import uuid, pathlib

    uid = get_current_user(request)["user_id"]
    uname = get_current_user(request)["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    amt = int(amount.replace(",", "")) if amount else 0
    if amt <= 0:
        return JSONResponse({"error": "금액을 입력해 주세요."}, status_code=400)

    purpose_info = next((p for p in SIMPLE_SLIP_PURPOSES if p[1] == purpose), None)
    if not purpose_info:
        return JSONResponse({"error": "용도를 선택해 주세요."}, status_code=400)

    purpose_label, account_code, account_name, is_expense = purpose_info

    if direction == "지출":
        slip_type = "출금"
        title = f"지출 {amt:,}원 - {purpose_label} / {partner or '미지정'}"
        lines = [
            (1, f"[{account_code}] {account_name}", account_code, amt, 0, partner, purpose_label),
            (2, "[101] 보통예금", "101", 0, amt, "", ""),
        ]
    else:
        slip_type = "입금"
        title = f"수입 {amt:,}원 - {purpose_label} / {partner or '미지정'}"
        lines = [
            (1, "[101] 보통예금", "101", amt, 0, "", ""),
            (2, f"[{account_code}] {account_name}", account_code, 0, amt, partner, purpose_label),
        ]

    saved_name = ""
    if attachment and attachment.filename:
        ext = pathlib.Path(attachment.filename).suffix
        content_bytes = await attachment.read()
        ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".hwp", ".txt", ".zip"}
        MAX_UPLOAD_SIZE = 10 * 1024 * 1024
        if ext.lower() not in ALLOWED_EXTENSIONS:
            return JSONResponse({"error": "허용되지 않는 파일 형식입니다."}, status_code=400)
        if len(content_bytes) > MAX_UPLOAD_SIZE:
            return JSONResponse({"error": "파일 크기가 10MB를 초과합니다."}, status_code=413)
        safe_name = f"{uuid.uuid4().hex}{ext}"
        upload_dir = pathlib.Path("static/uploads/erp")
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / safe_name).write_bytes(content_bytes)
        saved_name = f"{attachment.filename}|{safe_name}"

    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    year = now_kst().year

    conn = get_sqlite()
    try:
        cur = conn.execute(
            "INSERT INTO erp_docs (user_id, doc_type, title, content, attachment, status, dept, slip_type, slip_date, slip_total) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uid, "expense", title, memo, saved_name, doc_status, "", slip_type, slip_date, amt),
        )
        new_doc_id = cur.lastrowid
        seq = conn.execute("SELECT COUNT(*) FROM erp_docs WHERE doc_type='expense'").fetchone()[0]
        doc_number = f"EXP-{year}-{seq:04d}"
        conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, new_doc_id))

        for line_no, account, ac_code, debit, credit, ptr, summary in lines:
            conn.execute(
                "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
                (new_doc_id, line_no, account, ac_code, debit, credit, ptr, summary)
            )

        if is_draft:
            conn.execute(
                "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
                (new_doc_id, 0, uid, "기안", "pending")
            )
        else:
            conn.execute(
                "INSERT INTO approval_lines (doc_id, step, approver_id, role, status, acted_at) VALUES (?,?,?,?,?,?)",
                (new_doc_id, 0, uid, "기안", "approved", now)
            )
        conn.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
            (new_doc_id, 1, reviewer_id, "검토", "pending")
        )
        conn.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
            (new_doc_id, 2, approver_id, "승인", "pending")
        )
        conn.execute(
            "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
            (new_doc_id, uid, uname, "임시저장" if is_draft else "기안 (간편)", "")
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/erp_fa", status_code=303)


@router.post("/api/slip")
async def create_slip(
    request: Request,
    title: str = Form(""), content: str = Form(""),
    slip_type: str = Form(""), slip_date: str = Form(""),
    dept: str = Form(""),
    reviewer_id: int = Form(...),
    approver_id: int = Form(...),
    line_count: str = Form(""),
    attachment: Optional[UploadFile] = File(None),
    save_mode: str = Form("submit"),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    import uuid, pathlib
    uid = get_current_user(request)["user_id"]
    uname = get_current_user(request)["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    form = await request.form()
    line_nums = [n.strip() for n in line_count.split(",") if n.strip()]
    lines = []
    for i, ln in enumerate(line_nums):
        account = form.get(f"account_{ln}", "")
        account_code = form.get(f"account_code_{ln}", "")
        debit = int(form.get(f"debit_{ln}", 0) or 0)
        credit = int(form.get(f"credit_{ln}", 0) or 0)
        partner = form.get(f"partner_{ln}", "")
        summary = form.get(f"summary_{ln}", "")
        if account:
            lines.append((i + 1, account, account_code, debit, credit, partner, summary))

    total_debit = sum(l[3] for l in lines)
    total_credit = sum(l[4] for l in lines)
    if total_debit != total_credit:
        return JSONResponse({"error": "차변·대변 합계가 일치하지 않습니다."}, status_code=400)

    saved_name = ""
    if attachment and attachment.filename:
        ext = pathlib.Path(attachment.filename).suffix
        content_bytes = await attachment.read()
        ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".hwp", ".txt", ".zip"}
        MAX_UPLOAD_SIZE = 10 * 1024 * 1024
        if ext.lower() not in ALLOWED_EXTENSIONS:
            return JSONResponse({"error": "허용되지 않는 파일 형식입니다."}, status_code=400)
        if len(content_bytes) > MAX_UPLOAD_SIZE:
            return JSONResponse({"error": "파일 크기가 10MB를 초과합니다."}, status_code=413)
        safe_name = f"{uuid.uuid4().hex}{ext}"
        upload_dir = pathlib.Path("static/uploads/erp")
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / safe_name).write_bytes(content_bytes)
        saved_name = f"{attachment.filename}|{safe_name}"

    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    year = now_kst().year

    conn = get_sqlite()
    try:
        cur = conn.execute(
            "INSERT INTO erp_docs (user_id, doc_type, title, content, attachment, status, dept, slip_type, slip_date, slip_total) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uid, "expense", title, content, saved_name, doc_status, dept, slip_type, slip_date, total_debit),
        )
        new_doc_id = cur.lastrowid
        seq = conn.execute("SELECT COUNT(*) FROM erp_docs WHERE doc_type='expense'").fetchone()[0]
        doc_number = f"EXP-{year}-{seq:04d}"
        conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, new_doc_id))

        for line_no, account, account_code, debit, credit, partner, summary in lines:
            conn.execute(
                "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
                (new_doc_id, line_no, account, account_code, debit, credit, partner, summary)
            )

        if is_draft:
            conn.execute(
                "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
                (new_doc_id, 0, uid, "기안", "pending")
            )
        else:
            conn.execute(
                "INSERT INTO approval_lines (doc_id, step, approver_id, role, status, acted_at) VALUES (?,?,?,?,?,?)",
                (new_doc_id, 0, uid, "기안", "approved", now)
            )
        conn.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
            (new_doc_id, 1, reviewer_id, "검토", "pending")
        )
        conn.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
            (new_doc_id, 2, approver_id, "승인", "pending")
        )
        conn.execute(
            "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
            (new_doc_id, uid, uname, "임시저장" if is_draft else "기안", "")
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/erp_fa", status_code=303)


@router.get("/erp_doc/{doc_id}", response_class=HTMLResponse)
async def erp_doc_detail(request: Request, doc_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        row = conn.execute(
            """SELECT e.*,
                   u.name AS author_name, u.dept AS author_dept,
                   u.position AS author_position, u.phone AS author_phone,
                   u2.name AS approver_name
               FROM erp_docs e
               LEFT JOIN users u ON e.user_id = u.id
               LEFT JOIN users u2 ON e.approved_by = u2.id
               WHERE e.id=?""",
            (doc_id,)
        ).fetchone()
        if not row:
            return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2><a href='/'>홈으로</a>", status_code=404)
        lines = conn.execute("""
    SELECT al.*, u.name as user_name, u.dept as user_dept, u.position as user_position
    FROM approval_lines al
    LEFT JOIN users u ON al.approver_id = u.id
    WHERE al.doc_id=?
    ORDER BY al.step
""", (doc_id,)).fetchall()
        approval_lines = [dict(l) for l in lines]
        history = conn.execute("""
    SELECT * FROM doc_history WHERE doc_id=? ORDER BY created_at
""", (doc_id,)).fetchall()
        history = [dict(h) for h in history]
        slip_lines = []
        try:
            slip_rows = conn.execute(
                "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
            ).fetchall()
            slip_lines = [dict(s) for s in slip_rows]
        except Exception:
            pass
        extra_fields = {}
        raw_extra = dict(row).get("extra_fields", "{}")
        if raw_extra and raw_extra != "{}":
            try:
                extra_fields = json.loads(raw_extra)
            except Exception:
                pass
        try:
            dt_row = conn.execute(
                "SELECT form_schema FROM document_types WHERE name=?", (dict(row)["doc_type"],)
            ).fetchone()
            form_schema = json.loads(dt_row["form_schema"]) if dt_row and dt_row["form_schema"] else {}
        except Exception:
            form_schema = {}
        field_labels = {}
        if form_schema.get("fields"):
            field_labels = {f["name"]: f["label"] for f in form_schema["fields"]}
    finally:
        conn.close()
    doc = with_status_meta([row])[0]
    doc["doc_type_label"] = ERP_DOC_TYPE_LABELS.get(doc["doc_type"], doc["doc_type"])
    back_url = ERP_REDIRECTS.get(doc["doc_type"], "/erp_groupware")
    print_mode = request.query_params.get("print", "") == "1"
    uid = get_current_user(request)["user_id"]
    active_line = next((l for l in approval_lines if l["status"] == "pending"), None)
    can_approve = False
    if active_line:
        can_approve = (active_line["approver_id"] == uid)
    user_role = request.session.get("user_role", "")
    if user_role in ("admin", "manager"):
        can_approve = True
    if doc.get("status") in ("done", "approved", "resolved", "rejected"):
        can_approve = False
    return templates.TemplateResponse(
        request=request, name="erp/erp_doc_detail.html", context={
            "request": request, "page_title": doc["title"],
            "doc": doc, "back_url": back_url,
            "user_name": get_current_user(request)["user_name"],
            "approval_lines": approval_lines,
            "history": history,
            "print_mode": print_mode,
            "can_approve": can_approve,
            "current_user_id": uid,
            "slip_lines": slip_lines,
            "extra_fields": extra_fields,
            "field_labels": field_labels,
        }
    )


@router.get("/leave_approvals", response_class=HTMLResponse)
async def leave_approvals(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='hr_task' AND title LIKE '%휴가%' ORDER BY id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/leave_approvals.html", context={
        "request": request, "page_title": "휴가 승인",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "role": request.session.get("user_role", ""),
    })


@router.get("/recruitment_status", response_class=HTMLResponse)
async def recruitment_status(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="erp/recruitment_status.html", context={
        "request": request, "page_title": "채용 현황",
        "user_name": get_current_user(request)["user_name"], "postings": [],
    })


@router.get("/outflow_list", response_class=HTMLResponse)
async def outflow_list(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='expense' AND status IN ('done','approved') ORDER BY id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "출금 완료 내역",
        "subtitle": "처리 완료된 지출 내역입니다.",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
    })


@router.get("/pending_payments", response_class=HTMLResponse)
async def pending_payments(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='expense' AND status IN ('wait','pending','urgent') ORDER BY id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "미결제 내역",
        "subtitle": "처리 대기 중인 지출 요청입니다.",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
    })


@router.get("/production_status", response_class=HTMLResponse)
async def production_status(request: Request, all: int = 0):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        if all == 1:
            query = "SELECT * FROM erp_docs WHERE doc_type='work_order' ORDER BY id DESC"
        else:
            query = "SELECT * FROM erp_docs WHERE doc_type='work_order' AND status IN ('progress','wait') ORDER BY id DESC"
        docs = with_status_meta(conn.execute(query).fetchall())
    finally:
        conn.close()
    if all == 1:
        page_title = "전체 작업지시"
        subtitle = "전체 작업 지시 목록입니다."
    else:
        page_title = "작업 진행 현황"
        subtitle = "진행 중이거나 대기 중인 작업 지시입니다."
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": page_title,
        "subtitle": subtitle,
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "back_url": "/erp_product", "back_label": "생산관리",
    })


@router.get("/equipment_alerts", response_class=HTMLResponse)
async def equipment_alerts(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='work_order' AND status='urgent' ORDER BY id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "생산 긴급 알림",
        "subtitle": "긴급 처리가 필요한 작업 지시입니다.",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "back_url": "/erp_product", "back_label": "생산관리",
    })


@router.get("/po_status", response_class=HTMLResponse)
async def po_status(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='po' ORDER BY id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "발주 현황",
        "subtitle": "전체 발주서 목록입니다.",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "back_url": "/erp_purch", "back_label": "구매관리",
    })


@router.get("/delayed_delivery", response_class=HTMLResponse)
async def delayed_delivery(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='po' AND status='urgent' ORDER BY id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "납기 지연",
        "subtitle": "납기가 지연되어 긴급 확인이 필요한 발주입니다.",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "back_url": "/erp_purch", "back_label": "구매관리",
    })


@router.get("/po_pending", response_class=HTMLResponse)
async def po_pending(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='po' AND status IN ('wait','pending','urgent','progress') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 WHEN 'wait' THEN 2 ELSE 3 END, id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "발주 진행 현황",
        "subtitle": "진행 중인 발주 요청 목록입니다.",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "back_url": "/erp_purch", "back_label": "구매관리",
    })


@router.get("/outbound_status", response_class=HTMLResponse)
async def outbound_status(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='stock_move' ORDER BY id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "입출고 현황",
        "subtitle": "전체 입출고 등록 내역입니다.",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "back_url": "/erp_inventory", "back_label": "재고관리",
    })


@router.get("/low_stock_alerts", response_class=HTMLResponse)
async def low_stock_alerts(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='stock_move' AND status='urgent' ORDER BY id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "재고 부족 알림",
        "subtitle": "긴급 보충이 필요한 재고 항목입니다.",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "back_url": "/erp_inventory", "back_label": "재고관리",
    })


@router.get("/sales_leads", response_class=HTMLResponse)
async def sales_leads(request: Request, all: int = 0):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        if all == 1:
            query = "SELECT * FROM erp_docs WHERE doc_type='activity' ORDER BY id DESC"
        else:
            query = "SELECT * FROM erp_docs WHERE doc_type='activity' AND status IN ('progress','wait') ORDER BY id DESC"
        docs = with_status_meta(conn.execute(query).fetchall())
    finally:
        conn.close()
    if all == 1:
        page_title = "전체 영업 활동"
        subtitle = "전체 영업 활동 목록입니다."
    else:
        page_title = "영업 기회"
        subtitle = "진행 중인 영업 활동입니다."
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": page_title,
        "subtitle": subtitle,
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "back_url": "/erp_scrm", "back_label": "영업/고객관리",
    })


@router.get("/voc_list", response_class=HTMLResponse)
async def voc_list(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE doc_type='activity' AND status='urgent' ORDER BY id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "고객 VOC",
        "subtitle": "긴급 대응이 필요한 고객 요청입니다.",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "back_url": "/erp_scrm", "back_label": "영업/고객관리",
    })


@router.get("/approval_pending", response_class=HTMLResponse)
async def approval_pending(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            "SELECT * FROM erp_docs WHERE status IN ('wait','pending','urgent') ORDER BY CASE status WHEN 'urgent' THEN 0 ELSE 1 END, id DESC"
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/approval_pending.html", context={
        "request": request, "page_title": "결재 대기",
        "user_name": get_current_user(request)["user_name"], "docs": docs,
        "role": request.session.get("user_role", ""),
        "labels": ERP_DOC_TYPE_LABELS,
    })


# ERP 문서 API

@router.post("/api/erp_docs")
async def create_erp_doc(
    request: Request,
    doc_type: str = Form(""), title: str = Form(""), content: str = Form(""),
    visibility: str = Form("공개"),
    retention_period: str = Form("3년"),
    effective_date: str = Form(""),
    dept: str = Form(""),
    reviewer_id: int = Form(...),
    approver_id: int = Form(...),
    attachment: Optional[UploadFile] = File(None),
    save_mode: str = Form("submit"),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    import uuid, pathlib
    uid = get_current_user(request)["user_id"]
    saved_name = ""
    if attachment and attachment.filename:
        ext = pathlib.Path(attachment.filename).suffix
        content_bytes = await attachment.read()
        ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".hwp", ".txt", ".zip"}
        MAX_UPLOAD_SIZE = 10 * 1024 * 1024
        if ext.lower() not in ALLOWED_EXTENSIONS:
            return JSONResponse({"error": "허용되지 않는 파일 형식입니다."}, status_code=400)
        if len(content_bytes) > MAX_UPLOAD_SIZE:
            return JSONResponse({"error": "파일 크기가 10MB를 초과합니다."}, status_code=413)
        safe_name = f"{uuid.uuid4().hex}{ext}"
        upload_dir = pathlib.Path("static/uploads/erp")
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / safe_name
        dest.write_bytes(content_bytes)
        saved_name = f"{attachment.filename}|{safe_name}"
    form_data = await request.form()
    known_fields = {"doc_type", "title", "content", "visibility", "retention_period",
                    "effective_date", "dept", "reviewer_id", "approver_id", "attachment", "save_mode"}
    extra = {k: str(form_data[k]) for k in form_data if k not in known_fields and not hasattr(form_data[k], 'read')}
    extra_json = json.dumps(extra, ensure_ascii=False) if extra else "{}"
    DOC_NUM_PREFIXES = {"draft": "GW", "hr_task": "HR", "stock_move": "INV", "work_order": "WO", "po": "PO", "activity": "CRM", "expense": "EXP"}
    prefix = DOC_NUM_PREFIXES.get(doc_type, "DOC")
    year = now_kst().year
    uname = get_current_user(request)["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    conn = get_sqlite()
    try:
        cur = conn.execute(
            "INSERT INTO erp_docs (user_id, doc_type, title, content, attachment, status, visibility, retention_period, effective_date, dept, extra_fields) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (uid, doc_type, title, content, saved_name, doc_status, visibility, retention_period, effective_date, dept, extra_json),
        )
        new_doc_id = cur.lastrowid
        seq = conn.execute("SELECT COUNT(*) FROM erp_docs WHERE doc_type=?", (doc_type,)).fetchone()[0]
        doc_number = f"{prefix}-{year}-{seq:04d}"
        conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, new_doc_id))
        if is_draft:
            conn.execute(
                "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
                (new_doc_id, 0, uid, "기안", "pending")
            )
        else:
            conn.execute(
                "INSERT INTO approval_lines (doc_id, step, approver_id, role, status, acted_at) VALUES (?,?,?,?,?,?)",
                (new_doc_id, 0, uid, "기안", "approved", now)
            )
        conn.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
            (new_doc_id, 1, reviewer_id, "검토", "pending")
        )
        conn.execute(
            "INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
            (new_doc_id, 2, approver_id, "승인", "pending")
        )
        history_action = "임시저장" if is_draft else "기안"
        conn.execute(
            "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
            (new_doc_id, uid, uname, history_action, "")
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url=ERP_REDIRECTS.get(doc_type, "/"), status_code=303)


@router.post("/api/erp_docs/{doc_id}/status")
async def update_erp_doc_status(request: Request, doc_id: int, status: str = Form(...), reason: str = Form("")):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    user_role = request.session.get("user_role", "")
    if user_role not in ("admin", "manager"):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)

    u = get_current_user(request)
    uid = u["user_id"]
    uname = u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_sqlite()
    try:
        conn.execute(
            "UPDATE erp_docs SET status=?, approved_by=?, approved_at=? WHERE id=?",
            (status, uid, now, doc_id)
        )
        if status == "rejected" and reason:
            conn.execute("UPDATE erp_docs SET reject_reason=? WHERE id=?", (reason, doc_id))

        conn.execute(
            """UPDATE approval_lines SET status=?, comment=?, acted_at=?
               WHERE id = (SELECT id FROM approval_lines
                           WHERE doc_id=? AND status='pending' ORDER BY step LIMIT 1)""",
            (status, reason, now, doc_id)
        )

        action = "승인" if status in ("done", "approved") else "반려"
        conn.execute(
            "INSERT INTO doc_history (doc_id, action, user_id, user_name, comment) VALUES (?,?,?,?,?)",
            (doc_id, action, uid, uname, reason)
        )

        conn.commit()
    finally:
        conn.close()

    return JSONResponse({"ok": True})


@router.post("/api/erp_docs/{doc_id}/approve")
async def approve_erp_doc(request: Request, doc_id: int, comment: str = Form("")):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    u = get_current_user(request)
    uid, uname = u["user_id"], u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_sqlite()
    try:
        user_role = request.session.get("user_role", "")
        if user_role in ("admin", "manager"):
            line = conn.execute(
                "SELECT * FROM approval_lines WHERE doc_id=? AND status='pending' ORDER BY step LIMIT 1",
                (doc_id,)
            ).fetchone()
        else:
            line = conn.execute(
                "SELECT * FROM approval_lines WHERE doc_id=? AND approver_id=? AND status='pending'",
                (doc_id, uid)
            ).fetchone()

        if not line:
            return JSONResponse({"error": "승인할 항목이 없습니다."}, status_code=400)

        conn.execute(
            "UPDATE approval_lines SET status='approved', comment=?, acted_at=? WHERE id=?",
            (comment, now, line["id"])
        )

        total = conn.execute("SELECT COUNT(*) FROM approval_lines WHERE doc_id=?", (doc_id,)).fetchone()[0]
        approved = conn.execute("SELECT COUNT(*) FROM approval_lines WHERE doc_id=? AND status='approved'", (doc_id,)).fetchone()[0]
        new_status = "done" if approved >= total else "progress"

        conn.execute("UPDATE erp_docs SET status=?, approved_by=?, approved_at=? WHERE id=?",
                     (new_status, uid, now, doc_id))

        conn.execute(
            "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
            (doc_id, uid, uname, "승인", comment)
        )
        conn.commit()
    finally:
        conn.close()
    return JSONResponse({"ok": True, "new_status": new_status})


@router.post("/api/erp_docs/{doc_id}/reject")
async def reject_erp_doc(request: Request, doc_id: int, comment: str = Form(...)):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    u = get_current_user(request)
    uid, uname = u["user_id"], u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_sqlite()
    try:
        user_role = request.session.get("user_role", "")
        if user_role in ("admin", "manager"):
            line = conn.execute(
                "SELECT * FROM approval_lines WHERE doc_id=? AND status='pending' ORDER BY step LIMIT 1",
                (doc_id,)
            ).fetchone()
        else:
            line = conn.execute(
                "SELECT * FROM approval_lines WHERE doc_id=? AND approver_id=? AND status='pending'",
                (doc_id, uid)
            ).fetchone()

        if not line:
            return JSONResponse({"error": "반려할 항목이 없습니다."}, status_code=400)

        conn.execute(
            "UPDATE approval_lines SET status='rejected', comment=?, acted_at=? WHERE id=?",
            (comment, now, line["id"])
        )
        conn.execute(
            "UPDATE erp_docs SET status='rejected', reject_reason=?, approved_by=?, approved_at=? WHERE id=?",
            (comment, uid, now, doc_id)
        )
        conn.execute(
            "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
            (doc_id, uid, uname, "반려", comment)
        )
        conn.commit()
    finally:
        conn.close()
    return JSONResponse({"ok": True})


@router.post("/api/erp_docs/{doc_id}/submit")
async def submit_erp_doc(request: Request, doc_id: int):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    u = get_current_user(request)
    uid, uname = u["user_id"], u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_sqlite()
    try:
        doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            return JSONResponse({"error": "문서를 찾을 수 없습니다."}, status_code=404)
        if doc["user_id"] != uid:
            return JSONResponse({"error": "기안자만 상신할 수 있습니다."}, status_code=403)
        if doc["status"] != "draft":
            return JSONResponse({"error": "임시저장 상태의 문서만 상신할 수 있습니다."}, status_code=400)

        conn.execute("UPDATE erp_docs SET status='wait' WHERE id=?", (doc_id,))
        conn.execute(
            "UPDATE approval_lines SET status='approved', acted_at=? WHERE doc_id=? AND step=0",
            (now, doc_id)
        )
        conn.execute(
            "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
            (doc_id, uid, uname, "상신", "")
        )
        conn.commit()
    finally:
        conn.close()
    return JSONResponse({"ok": True})


@router.post("/api/erp_docs/{doc_id}/withdraw")
async def withdraw_erp_doc(request: Request, doc_id: int):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    u = get_current_user(request)
    uid, uname = u["user_id"], u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_sqlite()
    try:
        doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            return JSONResponse({"error": "문서를 찾을 수 없습니다."}, status_code=404)
        if doc["user_id"] != uid:
            return JSONResponse({"error": "기안자만 철회할 수 있습니다."}, status_code=403)
        if doc["status"] in ("done", "approved", "resolved", "rejected"):
            return JSONResponse({"error": "완료 또는 반려된 문서는 철회할 수 없습니다."}, status_code=400)

        last_line = conn.execute(
            "SELECT * FROM approval_lines WHERE doc_id=? ORDER BY step DESC LIMIT 1",
            (doc_id,)
        ).fetchone()
        if last_line and last_line["status"] == "approved":
            return JSONResponse({"error": "최종 결재가 완료된 문서는 철회할 수 없습니다."}, status_code=400)

        conn.execute("UPDATE erp_docs SET status='draft' WHERE id=?", (doc_id,))
        conn.execute(
            "UPDATE approval_lines SET status='pending', comment=NULL, acted_at=NULL WHERE doc_id=?",
            (doc_id,)
        )
        conn.execute(
            "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
            (doc_id, uid, uname, "철회", "기안자 철회")
        )
        conn.commit()
    finally:
        conn.close()
    return JSONResponse({"ok": True})


@router.get("/erp_doc/{doc_id}/print", response_class=HTMLResponse)
async def erp_doc_print(request: Request, doc_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    return RedirectResponse(url=f"/erp_doc/{doc_id}?print=1", status_code=303)


@router.get("/api/accounts")
async def api_accounts(request: Request):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    conn = get_sqlite()
    try:
        rows = conn.execute(
            "SELECT code, name, category, is_debit FROM accounts WHERE is_active=1 ORDER BY code"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@router.get("/api/partners")
async def api_partners(request: Request):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    conn = get_sqlite()
    try:
        rows = conn.execute(
            "SELECT code, name, biz_no, representative, biz_type, biz_item FROM partners WHERE is_active=1 ORDER BY code"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@router.get("/slip_list", response_class=HTMLResponse)
async def slip_list(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        docs = with_status_meta(conn.execute(
            """SELECT e.*, u.name as author_name
               FROM erp_docs e
               LEFT JOIN users u ON e.user_id = u.id
               WHERE e.doc_type='expense' AND e.slip_type != ''
               ORDER BY e.id DESC"""
        ).fetchall())
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/slip_list.html", context={
        "request": request, "page_title": "전표 조회",
        "user_name": get_current_user(request)["user_name"],
        "docs": docs,
    })


@router.get("/edit_slip/{doc_id}", response_class=HTMLResponse)
async def edit_slip(request: Request, doc_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
        if doc["user_id"] != uid:
            return HTMLResponse("<h2>본인 문서만 수정할 수 있습니다</h2>", status_code=403)
        if doc["status"] != "draft":
            return HTMLResponse("<h2>임시저장 상태의 문서만 수정할 수 있습니다</h2>", status_code=400)
        slip_lines_rows = [dict(s) for s in conn.execute(
            "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
        ).fetchall()]
        users = [dict(u) for u in conn.execute(
            "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
        ).fetchall()]
        approval = [dict(a) for a in conn.execute(
            "SELECT * FROM approval_lines WHERE doc_id=? ORDER BY step", (doc_id,)
        ).fetchall()]
    finally:
        conn.close()
    doc = dict(doc)
    reviewer_id = next((a["approver_id"] for a in approval if a["role"] == "검토"), "")
    approver_id = next((a["approver_id"] for a in approval if a["role"] == "승인"), "")
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_form.html", context={
            "request": request, "page_title": "전표 수정",
            "user_name": get_current_user(request)["user_name"],
            "users": users,
            "edit_mode": True, "doc": doc,
            "slip_lines": slip_lines_rows,
            "reviewer_id": reviewer_id, "approver_id": approver_id,
        }
    )


@router.post("/api/slip/{doc_id}")
async def update_slip(
    request: Request, doc_id: int,
    title: str = Form(""), content: str = Form(""),
    slip_type: str = Form(""), slip_date: str = Form(""),
    dept: str = Form(""),
    reviewer_id: int = Form(...),
    approver_id: int = Form(...),
    line_count: str = Form(""),
    attachment: Optional[UploadFile] = File(None),
    save_mode: str = Form("submit"),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    uid = get_current_user(request)["user_id"]
    uname = get_current_user(request)["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_sqlite()
    try:
        doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
        if not doc or doc["user_id"] != uid or doc["status"] != "draft":
            return JSONResponse({"error": "수정할 수 없는 문서입니다."}, status_code=400)
        form = await request.form()
        line_nums = [n.strip() for n in line_count.split(",") if n.strip()]
        lines = []
        for i, ln in enumerate(line_nums):
            account = form.get(f"account_{ln}", "")
            account_code = form.get(f"account_code_{ln}", "")
            debit = int(form.get(f"debit_{ln}", 0) or 0)
            credit = int(form.get(f"credit_{ln}", 0) or 0)
            partner = form.get(f"partner_{ln}", "")
            summary = form.get(f"summary_{ln}", "")
            if account:
                lines.append((i + 1, account, account_code, debit, credit, partner, summary))
        total_debit = sum(l[3] for l in lines)
        total_credit = sum(l[4] for l in lines)
        if total_debit != total_credit:
            return JSONResponse({"error": "차변·대변 합계가 일치하지 않습니다."}, status_code=400)

        import uuid, pathlib
        saved_name = doc["attachment"] or ""
        if attachment and attachment.filename:
            ext = pathlib.Path(attachment.filename).suffix
            content_bytes = await attachment.read()
            ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".hwp", ".txt", ".zip"}
            MAX_UPLOAD_SIZE = 10 * 1024 * 1024
            if ext.lower() not in ALLOWED_EXTENSIONS:
                return JSONResponse({"error": "허용되지 않는 파일 형식입니다."}, status_code=400)
            if len(content_bytes) > MAX_UPLOAD_SIZE:
                return JSONResponse({"error": "파일 크기가 10MB를 초과합니다."}, status_code=413)
            safe_name = f"{uuid.uuid4().hex}{ext}"
            upload_dir = pathlib.Path("static/uploads/erp")
            upload_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / safe_name).write_bytes(content_bytes)
            saved_name = f"{attachment.filename}|{safe_name}"

        is_draft = (save_mode == "draft")
        doc_status = "draft" if is_draft else "wait"
        conn.execute(
            "UPDATE erp_docs SET title=?, content=?, slip_type=?, slip_date=?, dept=?, slip_total=?, attachment=?, status=? WHERE id=?",
            (title, content, slip_type, slip_date, dept, total_debit, saved_name, doc_status, doc_id)
        )
        conn.execute("DELETE FROM slip_lines WHERE doc_id=?", (doc_id,))
        for line_no, account, account_code, debit, credit, partner, summary in lines:
            conn.execute(
                "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
                (doc_id, line_no, account, account_code, debit, credit, partner, summary)
            )
        conn.execute("DELETE FROM approval_lines WHERE doc_id=?", (doc_id,))
        if is_draft:
            conn.execute("INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
                         (doc_id, 0, uid, "기안", "pending"))
        else:
            conn.execute("INSERT INTO approval_lines (doc_id, step, approver_id, role, status, acted_at) VALUES (?,?,?,?,?,?)",
                         (doc_id, 0, uid, "기안", "approved", now))
        conn.execute("INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
                     (doc_id, 1, reviewer_id, "검토", "pending"))
        conn.execute("INSERT INTO approval_lines (doc_id, step, approver_id, role, status) VALUES (?,?,?,?,?)",
                     (doc_id, 2, approver_id, "승인", "pending"))
        conn.execute("INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
                     (doc_id, uid, uname, "수정", ""))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/erp_fa", status_code=303)


@router.post("/api/slip/{doc_id}/delete")
async def delete_slip(request: Request, doc_id: int):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    uid = get_current_user(request)["user_id"]
    conn = get_sqlite()
    try:
        doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            return JSONResponse({"error": "문서를 찾을 수 없습니다."}, status_code=404)
        if doc["user_id"] != uid:
            return JSONResponse({"error": "본인 문서만 삭제할 수 있습니다."}, status_code=403)
        if doc["status"] != "draft":
            return JSONResponse({"error": "임시저장 상태의 문서만 삭제할 수 있습니다."}, status_code=400)
        conn.execute("DELETE FROM slip_lines WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM approval_lines WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM doc_history WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM erp_docs WHERE id=?", (doc_id,))
        conn.commit()
    finally:
        conn.close()
    return JSONResponse({"ok": True})


@router.get("/erp_doc/{doc_id}/trade_statement", response_class=HTMLResponse)
async def trade_statement(request: Request, doc_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        doc = conn.execute(
            "SELECT e.*, u.name as author_name FROM erp_docs e LEFT JOIN users u ON e.user_id=u.id WHERE e.id=?",
            (doc_id,)
        ).fetchone()
        if not doc:
            return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
        slip_lines_data = [dict(s) for s in conn.execute(
            "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
        ).fetchall()]
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/trade_statement.html", context={
        "request": request, "doc": dict(doc), "slip_lines": slip_lines_data,
        "company": {"name": "(주)원플러스", "biz_no": "123-86-00001", "representative": "대표이사",
                     "address": "서울특별시 강남구 테헤란로 123", "biz_type": "서비스업", "biz_item": "소프트웨어 개발"},
    })


@router.get("/erp_doc/{doc_id}/receipt", response_class=HTMLResponse)
async def receipt(request: Request, doc_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        doc = conn.execute(
            "SELECT e.*, u.name as author_name FROM erp_docs e LEFT JOIN users u ON e.user_id=u.id WHERE e.id=?",
            (doc_id,)
        ).fetchone()
        if not doc:
            return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
        slip_lines_data = [dict(s) for s in conn.execute(
            "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
        ).fetchall()]
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/receipt.html", context={
        "request": request, "doc": dict(doc), "slip_lines": slip_lines_data,
        "company": {"name": "(주)원플러스", "biz_no": "123-86-00001", "representative": "대표이사",
                     "address": "서울특별시 강남구 테헤란로 123"},
    })


@router.get("/erp_doc/{doc_id}/tax_invoice", response_class=HTMLResponse)
async def tax_invoice(request: Request, doc_id: int):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    conn = get_sqlite()
    try:
        doc = conn.execute(
            "SELECT e.*, u.name as author_name FROM erp_docs e LEFT JOIN users u ON e.user_id=u.id WHERE e.id=?",
            (doc_id,)
        ).fetchone()
        if not doc:
            return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
        slip_lines_data = [dict(s) for s in conn.execute(
            "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
        ).fetchall()]
    finally:
        conn.close()
    return templates.TemplateResponse(request=request, name="erp/tax_invoice.html", context={
        "request": request, "doc": dict(doc), "slip_lines": slip_lines_data,
        "company": {"name": "(주)원플러스", "biz_no": "123-86-00001", "representative": "대표이사",
                     "address": "서울특별시 강남구 테헤란로 123", "biz_type": "서비스업", "biz_item": "소프트웨어 개발"},
    })


@router.get("/api/erp_docs")
async def list_erp_docs(request: Request, doc_type: Optional[str] = None):
    if not check_login(request):
        return JSONResponse({"error": "not logged in"}, status_code=401)
    conn = get_sqlite()
    try:
        if doc_type:
            rows = conn.execute("SELECT * FROM erp_docs WHERE doc_type=? ORDER BY created_at DESC", (doc_type,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM erp_docs ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# 보조기기 / 편의기능

class VoiceInput(BaseModel):
    text: str


@router.post("/api/text")
async def receive_voice_text(request: Request, data: VoiceInput):
    if not check_login(request):
        return {"error": "not logged in"}
    return {"status": "success", "received_text": data.text}


@router.get("/eyemouse", response_class=HTMLResponse)
async def eyemouse(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="worker/eyemouse.html", context={
        "request": request, "page_title": "아이 마우스",
        "user_name": get_current_user(request)["user_name"],
    })


@router.get("/real_trans", response_class=HTMLResponse)
async def real_trans(request: Request, requested: str = ""):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request=request, name="worker/realtime_trans.html", context={
        "request": request, "page_title": "실시간 자막",
        "user_name": get_current_user(request)["user_name"],
        "requested": requested == "1",
    })


@router.post("/api/trans_request")
async def trans_request(
    request: Request,
    translator_name: str = Form(...),
    service_type: str = Form(""),
    request_date: str = Form(""),
    request_time: str = Form(""),
    duration: str = Form(""),
    meeting_link: str = Form(""),
    details: str = Form(""),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    user = get_current_user(request)
    user_id = user["user_id"]
    conn = get_sqlite()
    try:
        conn.execute(
            """INSERT INTO trans_requests
               (user_id, translator_name, service_type, request_date, request_time, duration, meeting_link, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, translator_name, service_type, request_date, request_time, duration, meeting_link, details),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/real_trans?requested=1", status_code=303)
