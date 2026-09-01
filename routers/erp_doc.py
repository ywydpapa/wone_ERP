import json
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.db import with_status_meta
from core.deps import get_db, require_login, templates
from core.tz import now_kst
from core.constants import ERP_DOC_TYPE_LABELS, ERP_REDIRECTS
from routers._helpers import save_upload, insert_approval_lines

router = APIRouter()


@router.get("/erp_doc/{doc_id}", response_class=HTMLResponse)
async def erp_doc_detail(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
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
    doc = with_status_meta([row])[0]
    doc["doc_type_label"] = ERP_DOC_TYPE_LABELS.get(doc["doc_type"], doc["doc_type"])
    back_url = ERP_REDIRECTS.get(doc["doc_type"], "/erp_groupware")
    print_mode = request.query_params.get("print", "") == "1"
    uid = u["user_id"]
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
            "user_name": u["user_name"],
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
    u: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = u["user_id"]
    saved_name = await save_upload(attachment)
    if isinstance(saved_name, JSONResponse):
        return saved_name
    form_data = await request.form()
    known_fields = {"doc_type", "title", "content", "visibility", "retention_period",
                    "effective_date", "dept", "reviewer_id", "approver_id", "attachment", "save_mode"}
    extra = {k: str(form_data[k]) for k in form_data if k not in known_fields and not hasattr(form_data[k], 'read')}
    extra_json = json.dumps(extra, ensure_ascii=False) if extra else "{}"
    DOC_NUM_PREFIXES = {"draft": "GW", "hr_task": "HR", "stock_move": "INV", "work_order": "WO", "po": "PO", "activity": "CRM", "expense": "EXP"}
    prefix = DOC_NUM_PREFIXES.get(doc_type, "DOC")
    year = now_kst().year
    uname = u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    cur = conn.execute(
        "INSERT INTO erp_docs (user_id, doc_type, title, content, attachment, status, visibility, retention_period, effective_date, dept, extra_fields) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (uid, doc_type, title, content, saved_name, doc_status, visibility, retention_period, effective_date, dept, extra_json),
    )
    new_doc_id = cur.lastrowid
    seq = conn.execute("SELECT COUNT(*) FROM erp_docs WHERE doc_type=?", (doc_type,)).fetchone()[0]
    doc_number = f"{prefix}-{year}-{seq:04d}"
    conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, new_doc_id))
    insert_approval_lines(conn, new_doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, "임시저장" if is_draft else "기안")
    conn.commit()
    return RedirectResponse(url=ERP_REDIRECTS.get(doc_type, "/"), status_code=303)


@router.post("/api/erp_docs/{doc_id}/status")
async def update_erp_doc_status(request: Request, doc_id: int, status: str = Form(...), reason: str = Form(""), u: dict = Depends(require_login), conn = Depends(get_db)):
    user_role = request.session.get("user_role", "")
    if user_role not in ("admin", "manager"):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)

    uid = u["user_id"]
    uname = u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

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
    return JSONResponse({"ok": True})


@router.post("/api/erp_docs/{doc_id}/approve")
async def approve_erp_doc(request: Request, doc_id: int, comment: str = Form(""), u: dict = Depends(require_login), conn = Depends(get_db)):
    uid, uname = u["user_id"], u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

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
    return JSONResponse({"ok": True, "new_status": new_status})


@router.post("/api/erp_docs/{doc_id}/reject")
async def reject_erp_doc(request: Request, doc_id: int, comment: str = Form(...), u: dict = Depends(require_login), conn = Depends(get_db)):
    uid, uname = u["user_id"], u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

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
    return JSONResponse({"ok": True})


@router.post("/api/erp_docs/{doc_id}/submit")
async def submit_erp_doc(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid, uname = u["user_id"], u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

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
    return JSONResponse({"ok": True})


@router.post("/api/erp_docs/{doc_id}/withdraw")
async def withdraw_erp_doc(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid, uname = u["user_id"], u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

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
    return JSONResponse({"ok": True})


@router.get("/erp_doc/{doc_id}/print", response_class=HTMLResponse)
async def erp_doc_print(request: Request, doc_id: int, u: dict = Depends(require_login)):
    return RedirectResponse(url=f"/erp_doc/{doc_id}?print=1", status_code=303)


@router.get("/api/erp_docs")
async def list_erp_docs(request: Request, doc_type: Optional[str] = None, u: dict = Depends(require_login), conn = Depends(get_db)):
    if doc_type:
        rows = conn.execute("SELECT * FROM erp_docs WHERE doc_type=? ORDER BY created_at DESC", (doc_type,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM erp_docs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]
