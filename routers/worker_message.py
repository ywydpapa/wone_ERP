from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.books import book_of
from core.deps import get_db, get_employee_id, require_login, templates

router = APIRouter()

# 스태프 외에는 같은 장부 사용자와 스태프만 수신 대상
SAME_BOOK = """(role='platform_staff' OR id IN (
    SELECT user_id FROM client_users WHERE company_id=?
    UNION SELECT user_id FROM employees WHERE company_id=?))"""


@router.get("/newarrived_jobs", response_class=HTMLResponse)
async def newarrived_jobs(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    unread_msgs = [dict(m) for m in conn.execute(
        "SELECT * FROM messages WHERE user_id=? AND direction='in' AND is_read=0 ORDER BY id DESC", (uid,)).fetchall()]
    read_msgs = [dict(m) for m in conn.execute(
        "SELECT * FROM messages WHERE user_id=? AND direction='in' AND is_read=1 ORDER BY id DESC", (uid,)).fetchall()]
    sent_msgs = [dict(m) for m in conn.execute(
        "SELECT * FROM messages WHERE user_id=? AND direction='out' ORDER BY id DESC", (uid,)).fetchall()]
    return templates.TemplateResponse(
        request=request, name="worker/new_arrived_job.html", context={
            "request": request, "page_title": "메시지함",
            "user_name": u["name"],
            "unread_msgs": unread_msgs, "read_msgs": read_msgs, "sent_msgs": sent_msgs,
            "unread_count": len(unread_msgs), "read_count": len(read_msgs),
        }
    )


@router.get("/message/{msg_id}", response_class=HTMLResponse)
async def message_detail(request: Request, msg_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    row = conn.execute("SELECT * FROM messages WHERE id=? AND user_id=?", (msg_id, uid)).fetchone()
    if not row:
        return HTMLResponse("<h2>메시지를 찾을 수 없습니다</h2><a href='/newarrived_jobs'>돌아가기</a>", status_code=404)
    conn.execute("UPDATE messages SET is_read=1 WHERE id=?", (msg_id,))
    conn.commit()
    return templates.TemplateResponse(request=request, name="worker/message_detail.html", context={
        "request": request, "page_title": "메시지 상세",
        "user_name": u["name"],
        "msg": dict(row),
    })


@router.post("/api/messages/{msg_id}/reply")
async def reply_message(request: Request, msg_id: int, body: str = Form(...), u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    row = conn.execute("SELECT sender FROM messages WHERE id=? AND user_id=?", (msg_id, uid)).fetchone()
    if row:
        recipient = row["sender"]
        conn.execute(
            "INSERT INTO messages (user_id, sender, recipient, body, time_label, is_read, direction) VALUES (?,?,?,?,datetime('now','localtime'),1,'out')",
            (uid, u["name"], recipient, body),
        )
        conn.execute("UPDATE messages SET is_read=1 WHERE id=?", (msg_id,))
        conn.commit()
    return RedirectResponse(url="/newarrived_jobs", status_code=303)


@router.post("/api/messages/{msg_id}/read")
async def read_message(request: Request, msg_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    conn.execute("UPDATE messages SET is_read=1 WHERE id=?", (msg_id,))
    conn.commit()
    return {"ok": True}


@router.get("/api/dept/members")
async def dept_members(request: Request, dept: str, u: dict = Depends(require_login), conn = Depends(get_db)):
    sql, args = "SELECT name, position FROM users WHERE dept=?", [dept]
    if u["role"] != "platform_staff":
        book = book_of(conn, u)
        sql += " AND " + SAME_BOOK
        args += [book, book]
    rows = conn.execute(sql + " ORDER BY id", args).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/messages/thread")
async def message_thread(request: Request, with_name: str, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    rows = conn.execute(
        """SELECT sender, recipient, body, time_label, direction FROM messages
           WHERE user_id=? AND (
               (direction='out' AND recipient=?) OR
               (direction='in'  AND sender=?)
           )
           ORDER BY id DESC LIMIT 20""",
        (uid, with_name, with_name)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


# 담당자는 최근 업무 배정자 기준
@router.get("/api/messages/manager")
async def my_manager(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    row = conn.execute(
        """SELECT u.name FROM tasks t JOIN users u ON u.id=t.assigned_by
           WHERE t.assigned_to=? ORDER BY t.id DESC LIMIT 1""",
        (get_employee_id(conn, u["id"]),),
    ).fetchone()
    if not row:
        return JSONResponse({"error": "담당자가 없습니다."}, status_code=404)
    return {"name": row["name"]}


@router.get("/api/messages/contacts")
async def contacts(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    sql, args = "SELECT name FROM users WHERE id<>?", [u["id"]]
    if u["role"] != "platform_staff":
        book = book_of(conn, u)
        sql += " AND " + SAME_BOOK
        args += [book, book]
    return [r["name"] for r in conn.execute(sql + " ORDER BY name", args).fetchall()]


@router.post("/api/messages/send")
async def send_message(request: Request, to_name: str = Form(...), body: str = Form(...), u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    if not body.strip():
        return JSONResponse({"error": "내용을 입력해 주세요."}, status_code=400)
    sql, args = "SELECT id FROM users WHERE name=?", [to_name]
    if u["role"] != "platform_staff":
        book = book_of(conn, u)
        sql += " AND " + SAME_BOOK
        args += [book, book]
    recipient_row = conn.execute(sql, args).fetchone()
    if not recipient_row:
        return JSONResponse({"error": "받는 사람을 찾을 수 없습니다."}, status_code=400)
    conn.execute(
        "INSERT INTO messages (user_id, sender, recipient, body, time_label, is_read, direction) VALUES (?,?,?,?,datetime('now','localtime'),1,'out')",
        (uid, u["name"], to_name, body.strip())
    )
    conn.execute(
        "INSERT INTO messages (user_id, sender, recipient, body, time_label, is_read, direction) VALUES (?,?,?,?,datetime('now','localtime'),0,'in')",
        (recipient_row["id"], u["name"], to_name, body.strip())
    )
    conn.commit()
    return JSONResponse({"ok": True})


@router.post("/api/messages/read_all")
async def read_all_messages(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    conn.execute("UPDATE messages SET is_read=1 WHERE user_id=?", (uid,))
    conn.commit()
    return {"ok": True}
