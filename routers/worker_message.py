from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.deps import get_db, require_login, templates

router = APIRouter()


@router.get("/newarrived_jobs", response_class=HTMLResponse)
async def newarrived_jobs(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    unread_msgs = [dict(m) for m in conn.execute(
        "SELECT * FROM messages WHERE user_id=? AND direction='in' AND is_read=0 ORDER BY id DESC", (uid,)).fetchall()]
    read_msgs = [dict(m) for m in conn.execute(
        "SELECT * FROM messages WHERE user_id=? AND direction='in' AND is_read=1 ORDER BY id DESC", (uid,)).fetchall()]
    sent_msgs = [dict(m) for m in conn.execute(
        "SELECT * FROM messages WHERE user_id=? AND direction='out' ORDER BY id DESC", (uid,)).fetchall()]
    return templates.TemplateResponse(
        request=request, name="worker/new_arrived_job.html", context={
            "request": request, "page_title": "메시지함",
            "user_name": u["user_name"],
            "unread_msgs": unread_msgs, "read_msgs": read_msgs, "sent_msgs": sent_msgs,
            "unread_count": len(unread_msgs), "read_count": len(read_msgs),
        }
    )


@router.get("/message/{msg_id}", response_class=HTMLResponse)
async def message_detail(request: Request, msg_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    row = conn.execute("SELECT * FROM messages WHERE id=? AND user_id=?", (msg_id, uid)).fetchone()
    if not row:
        return HTMLResponse("<h2>메시지를 찾을 수 없습니다</h2><a href='/newarrived_jobs'>돌아가기</a>", status_code=404)
    conn.execute("UPDATE messages SET is_read=1 WHERE id=?", (msg_id,))
    conn.commit()
    return templates.TemplateResponse(request=request, name="worker/message_detail.html", context={
        "request": request, "page_title": "메시지 상세",
        "user_name": u["user_name"],
        "msg": dict(row),
    })


@router.post("/api/messages/{msg_id}/reply")
async def reply_message(request: Request, msg_id: int, body: str = Form(...), u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    row = conn.execute("SELECT sender FROM messages WHERE id=? AND user_id=?", (msg_id, uid)).fetchone()
    if row:
        recipient = row["sender"]
        conn.execute(
            "INSERT INTO messages (user_id, sender, recipient, body, time_label, is_read, direction) VALUES (?,?,?,?,datetime('now','localtime'),1,'out')",
            (uid, u["user_name"], recipient, body),
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
    rows = conn.execute(
        "SELECT name, position FROM users WHERE dept=? ORDER BY id", (dept,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/messages/thread")
async def message_thread(request: Request, with_name: str, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
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


@router.post("/api/messages/send")
async def send_message(request: Request, to_name: str = Form(...), body: str = Form(...), u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    if not body.strip():
        return JSONResponse({"error": "내용을 입력해 주세요."}, status_code=400)
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
    return JSONResponse({"ok": True})


@router.post("/api/messages/read_all")
async def read_all_messages(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    conn.execute("UPDATE messages SET is_read=1 WHERE user_id=?", (uid,))
    conn.commit()
    return {"ok": True}
