import json
import re
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core import audit, books
from core.approval import ACTING, box_sql, current_line, insert_lines, parse_lines, preset_lines
from core.books import book_of, require_book
from core.db import with_status_meta
from core.deps import get_db, require_login, templates
from core.notification import create_bulk_notifications, create_notification
from core.tz import now_kst
from core.constants import ERP_DOC_TYPES, ERP_DOC_TYPE_LABELS, ERP_REDIRECTS
from routers._helpers import save_upload, get_owned_doc

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
    if not row or (row["company_id"] != (book_of(conn, u) or 0)
                   and (row["doc_type"] == "expense" or u["role"] != "platform_staff")):
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2><a href='/'>홈으로</a>", status_code=404)
    uid = u["id"]
    user_role = request.session.get("role", "")
    own_client = row["doc_type"] == "expense" and user_role == "client"
    if user_role != "platform_staff" and not own_client and row["user_id"] != uid:
        is_approver = conn.execute(
            "SELECT 1 FROM approval_lines WHERE doc_id=? AND approver_id=?", (doc_id, uid)
        ).fetchone()
        if not is_approver:
            return HTMLResponse("<h2>접근 권한이 없습니다</h2><a href='/'>홈으로</a>", status_code=403)
    lines = conn.execute("""
    SELECT al.*, u.name as user_name, u.dept as user_dept, u.position as user_position
    FROM approval_lines al
    LEFT JOIN users u ON al.approver_id = u.id
    WHERE al.doc_id=?
    ORDER BY al.step
""", (doc_id,)).fetchall()
    approval_lines = [dict(l) for l in lines if l["role"] != "참조"]
    refs = [dict(l) for l in lines if l["role"] == "참조"]
    mine_ref = next((r for r in refs if r["approver_id"] == uid and not r["acted_at"]), None)
    if mine_ref and row["status"] != "draft":
        conn.execute("UPDATE approval_lines SET acted_at=? WHERE id=?",
                     (now_kst().strftime("%Y-%m-%d %H:%M:%S"), mine_ref["id"]))
        conn.commit()
    history = conn.execute("""
    SELECT * FROM doc_history WHERE doc_id=? ORDER BY created_at
""", (doc_id,)).fetchall()
    history = [dict(h) for h in history]
    slip_rows = conn.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()
    slip_lines = [dict(s) for s in slip_rows]

    total_debit = sum(sl.get('debit') or 0 for sl in slip_lines)
    total_credit = sum(sl.get('credit') or 0 for sl in slip_lines)
    is_balanced = total_debit == total_credit
    balance_diff = abs(total_debit - total_credit)

    attach = {}
    if dict(row).get('attachment'):
        parts = dict(row)['attachment'].split('|')
        orig_name = parts[0]
        saved_name = parts[1] if len(parts) > 1 else parts[0]
        ext = orig_name.rsplit('.', 1)[-1].lower() if '.' in orig_name else ''
        attach = {"orig_name": orig_name, "saved_name": saved_name,
                  "file_url": f"/files/erp/{saved_name}", "ext": ext}

    raw_extra = dict(row).get("extra_fields")
    extra_fields = json.loads(raw_extra) if raw_extra and raw_extra != "{}" else {}
    field_labels = {}
    tpl_id = dict(row).get("template_id")
    if tpl_id:
        tpl_row = conn.execute("SELECT fields FROM form_templates WHERE id = ?", (tpl_id,)).fetchone()
        if tpl_row:
            fields = json.loads(tpl_row["fields"] or "[]")
            field_labels = {f["name"]: f["label"] for f in fields}
    if not field_labels:
        dt_row = conn.execute(
            "SELECT form_schema FROM document_types WHERE name=?", (dict(row)["doc_type"],)
        ).fetchone()
        form_schema = json.loads(dt_row["form_schema"]) if dt_row and dt_row["form_schema"] else {}
        if form_schema.get("fields"):
            field_labels = {f["name"]: f["label"] for f in form_schema["fields"]}
    for al in approval_lines:
        al['acted_date'] = al['acted_at'][:10] if al.get('acted_at') else ''
    for h in history:
        h['created_short'] = h['created_at'][:16] if h.get('created_at') else ''

    doc = with_status_meta([row])[0]
    doc["created_date"] = doc["created_at"][:10] if doc.get("created_at") else "-"
    doc["doc_type_label"] = ERP_DOC_TYPE_LABELS.get(doc["doc_type"], doc["doc_type"])
    back_url = ERP_REDIRECTS.get(doc["doc_type"], "/erp_groupware")
    active_line = next((l for l in approval_lines if l["status"] == "pending" and l["role"] in ACTING), None)
    can_approve = bool(active_line) and doc["status"] in ("wait", "progress", "urgent") and (
        active_line["approver_id"] == uid or user_role == "platform_staff")
    can_final = can_approve and sum(1 for l in approval_lines if l["status"] == "pending" and l["role"] in ACTING) > 1
    can_confirm = doc["status"] == "done" and any(
        l["role"] == "후결" and l["status"] == "pending" and l["approver_id"] == uid for l in approval_lines)

    related_links = []
    content = doc.get("content") or ""
    title = doc.get("title") or ""
    combined = title + " " + content

    gr_match = re.search(r'(GR-\d+-\d+)', combined)
    if gr_match:
        gr_num = gr_match.group(1)
        gr_row = conn.execute("SELECT id FROM goods_receipts WHERE gr_number=?", (gr_num,)).fetchone()
        if gr_row:
            related_links.append({"label": f"입고 {gr_num}", "url": f"/goods-receipts/{gr_row[0]}"})

    ship_match = re.search(r'(SHP-\d+-\d+)', combined)
    if ship_match:
        ship_num = ship_match.group(1)
        ship_row = conn.execute("SELECT id FROM shipments WHERE ship_number=?", (ship_num,)).fetchone()
        if ship_row:
            related_links.append({"label": f"출고 {ship_num}", "url": f"/shipments/{ship_row[0]}"})

    is_auto = bool(re.search(r'자동\s*(생성\s*)?전표', content))
    slip_locked = bool(doc.get("slip_type")) and books.period_closed(conn, row["company_id"], doc.get("slip_date"))
    has_inv = bool(conn.execute("SELECT 1 FROM tax_invoices WHERE doc_id=? AND company_id=?", (doc_id, row["company_id"])).fetchone())
    reversed_by = conn.execute("SELECT id, slip_no FROM erp_docs WHERE reversal_of=?", (doc_id,)).fetchone()
    orig = None
    if doc.get("reversal_of"):
        orig = conn.execute("SELECT id, slip_no FROM erp_docs WHERE id=?", (doc["reversal_of"],)).fetchone()
    just_created = request.query_params.get("created") == "1"

    return templates.TemplateResponse(
        request=request, name="erp/erp_doc_detail.html", context={
            "request": request, "page_title": doc["title"],
            "doc": doc, "back_url": back_url, "just_created": just_created,
            "user_name": u["name"],
            "approval_lines": approval_lines,
            "history": history,
            "can_approve": can_approve,
            "can_final": can_final,
            "can_confirm": can_confirm,
            "refs": refs,
            "current_user_id": uid,
            "slip_lines": slip_lines,
            "total_debit": total_debit, "total_credit": total_credit,
            "is_balanced": is_balanced, "balance_diff": balance_diff,
            "attach": attach,
            "extra_fields": extra_fields,
            "field_labels": field_labels,
            "related_links": related_links,
            "is_auto": is_auto,
            "slip_locked": slip_locked,
            "has_inv": has_inv,
            "reversed_by": reversed_by,
            "orig": orig,
            "can_reverse": u["role"] in ("client", "platform_staff"),
            "today": now_kst().strftime("%Y-%m-%d"),
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
    attachment: UploadFile = File(None),
    template_id: int = Form(None),
    save_mode: str = Form("submit"),
    u: dict = Depends(require_login),
    conn = Depends(get_db),
):
    if doc_type == "expense":
        return JSONResponse({"error": "전표는 전표 입력 화면에서 작성해 주세요."}, status_code=400)
    uid = u["id"]
    form_data = await request.form()
    book = book_of(conn, u) or 0
    users = {x["id"] for x in books.book_users(conn, book) if x["id"] != uid}
    lines, err = parse_lines(form_data, users)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    saved_name = await save_upload(attachment)
    if isinstance(saved_name, JSONResponse):
        return saved_name
    known_fields = {"doc_type", "title", "content", "visibility", "retention_period", "effective_date", "dept",
                    "line_role", "line_user", "attachment", "save_mode", "template_id", "csrf_token"}
    extra = {k: str(form_data[k]) for k in form_data if k not in known_fields and not hasattr(form_data[k], 'read')}
    extra_json = json.dumps(extra, ensure_ascii=False) if extra else "{}"
    DOC_NUM_PREFIXES = {"draft": "GW", "hr_task": "HR", "stock_move": "INV", "work_order": "WO", "po": "PO", "activity": "CRM"}
    prefix = DOC_NUM_PREFIXES.get(doc_type, "DOC")
    year = now_kst().year
    uname = u["name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    cur = conn.execute(
        "INSERT INTO erp_docs (user_id, doc_type, title, content, attachment, status, visibility, retention_period, effective_date, dept, extra_fields, template_id, company_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, doc_type, title, content, saved_name, doc_status, visibility, retention_period, effective_date, dept, extra_json, template_id, book),
    )
    new_doc_id = cur.lastrowid
    doc_number = f"{prefix}-{year}-{new_doc_id:04d}"
    conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, new_doc_id))
    insert_lines(conn, new_doc_id, uid, lines, is_draft, now)
    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (new_doc_id, uid, uname, "임시저장" if is_draft else "기안", "")
    )
    if not is_draft:
        audit.log(conn, uid, "doc_submit", "doc", new_doc_id, f"{doc_number} {title}", company_id=book)
        line = current_line(conn, new_doc_id)
        if line:
            create_notification(conn, line["approver_id"], "결재 요청", title, f"/erp_doc/{new_doc_id}")
    conn.commit()
    return RedirectResponse(url=ERP_REDIRECTS.get(doc_type, "/"), status_code=303)


@router.post("/api/erp_docs/{doc_id}/status")
async def update_erp_doc_status(request: Request, doc_id: int, status: str = Form(...), reason: str = Form(""), u: dict = Depends(require_login), conn = Depends(get_db)):
    user_role = request.session.get("role", "")
    if user_role != "platform_staff":
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    doc = conn.execute("SELECT doc_type, doc_number, title, company_id FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
    if doc and doc["doc_type"] == "expense":
        return JSONResponse({"error": "전표는 결재로만 상태를 바꿀 수 있습니다."}, status_code=400)

    uid = u["id"]
    uname = u["name"]
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
    if doc:
        audit.log(conn, uid, "doc_approve" if action == "승인" else "doc_reject", "doc", doc_id,
                  f"{doc['doc_number']} {doc['title']}", company_id=doc["company_id"])

    conn.commit()
    return JSONResponse({"ok": True})


OPEN = ("wait", "pending", "progress", "urgent")


def _my_line(conn, doc, uid, staff):
    # 순번이 온 결재/합의 라인만. 스태프는 현재 순번 대리 처리
    line = current_line(conn, doc["id"]) if doc["status"] in OPEN else None
    if line and (line["approver_id"] == uid or staff):
        return line
    return None


@router.post("/api/erp_docs/{doc_id}/approve")
async def approve_erp_doc(request: Request, doc_id: int, comment: str = Form(""), final: int = Form(0),
                          u: dict = Depends(require_login), conn = Depends(get_db)):
    uid, uname = u["id"], u["name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
    if not doc or (doc["company_id"] != (book_of(conn, u) or 0)
                   and (doc["doc_type"] == "expense" or u["role"] != "platform_staff")):
        return JSONResponse({"error": "문서를 찾을 수 없습니다."}, status_code=404)

    if doc["status"] == "done":
        post = conn.execute(
            "SELECT id FROM approval_lines WHERE doc_id=? AND approver_id=? AND role='후결' AND status='pending'",
            (doc_id, uid)
        ).fetchone()
        if not post:
            return JSONResponse({"error": "승인할 항목이 없습니다."}, status_code=400)
        conn.execute("UPDATE approval_lines SET status='approved', comment=?, acted_at=? WHERE id=?", (comment, now, post["id"]))
        conn.execute(
            "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
            (doc_id, uid, uname, "후결", comment)
        )
        audit.log(conn, uid, "doc_approve", "doc", doc_id, f"{doc['doc_number']} {doc['title']}", company_id=doc["company_id"])
        conn.commit()
        return JSONResponse({"ok": True, "new_status": "done"})

    line = _my_line(conn, doc, uid, request.session.get("role", "") == "platform_staff")
    if not line:
        return JSONResponse({"error": "승인할 항목이 없습니다."}, status_code=400)

    rest = [r["id"] for r in conn.execute(
        f"SELECT id FROM approval_lines WHERE doc_id=? AND status='pending' AND step > ? AND role IN ({','.join('?' * len(ACTING))})",
        (doc_id, line["step"], *ACTING)
    )]
    final = bool(final and rest)
    new_status = "done" if final or not rest else "progress"
    posting = new_status == "done" and doc["doc_type"] == "expense"
    if posting and books.period_closed(conn, doc["company_id"], doc["slip_date"]):
        return JSONResponse({"error": "마감된 회계기간입니다."}, status_code=400)
    if posting:
        lines = [
            {"code": r["account_code"], "debit": r["debit"] or 0, "credit": r["credit"] or 0,
             "partner_id": r["partner_id"], "dept": r["dept"] or ""}
            for r in conn.execute("SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,))
        ]
        err = books.check_lines(conn, doc["company_id"], lines)
        if err:
            return JSONResponse({"error": err}, status_code=400)

    conn.execute(
        "UPDATE approval_lines SET status=?, comment=?, acted_at=? WHERE id=?",
        ("final" if final else "approved", comment, now, line["id"])
    )
    if final:
        conn.executemany("UPDATE approval_lines SET status='skipped' WHERE id=?", [(i,) for i in rest])
    conn.execute("UPDATE erp_docs SET status=?, approved_by=?, approved_at=?, posted_at=? WHERE id=?",
                 (new_status, uid, now, now if posting else doc["posted_at"], doc_id))

    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (doc_id, uid, uname, "전결" if final else "승인", comment)
    )
    audit.log(conn, uid, "doc_approve", "doc", doc_id, f"{doc['doc_number']} {doc['title']}", company_id=doc["company_id"])
    if new_status == "progress":
        nxt = current_line(conn, doc_id)
        if nxt:
            create_notification(conn, nxt["approver_id"], "결재 요청", doc["title"], f"/erp_doc/{doc_id}")
    else:
        create_notification(conn, doc["user_id"], "결재 완료", doc["title"], f"/erp_doc/{doc_id}")
        ref_ids = [r["approver_id"] for r in conn.execute(
            "SELECT approver_id FROM approval_lines WHERE doc_id=? AND role='참조'", (doc_id,)
        )]
        if ref_ids:
            create_bulk_notifications(conn, ref_ids, "결재 완료(참조)", doc["title"], f"/erp_doc/{doc_id}")
    conn.commit()
    return JSONResponse({"ok": True, "new_status": new_status})


@router.post("/api/erp_docs/{doc_id}/reject")
async def reject_erp_doc(request: Request, doc_id: int, comment: str = Form(...), u: dict = Depends(require_login), conn = Depends(get_db)):
    uid, uname = u["id"], u["name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
    if not doc or (doc["company_id"] != (book_of(conn, u) or 0)
                   and (doc["doc_type"] == "expense" or u["role"] != "platform_staff")):
        return JSONResponse({"error": "문서를 찾을 수 없습니다."}, status_code=404)
    line = _my_line(conn, doc, uid, request.session.get("role", "") == "platform_staff")
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
    audit.log(conn, uid, "doc_reject", "doc", doc_id, f"{doc['doc_number']} {doc['title']}", company_id=doc["company_id"])
    create_notification(conn, doc["user_id"], "결재 반려", doc["title"], f"/erp_doc/{doc_id}")
    conn.commit()
    return JSONResponse({"ok": True})


@router.post("/api/erp_docs/{doc_id}/submit")
async def submit_erp_doc(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid, uname = u["id"], u["name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    doc, err = get_owned_doc(conn, doc_id, uid)
    if err:
        return err
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
    audit.log(conn, uid, "doc_submit", "doc", doc_id, f"{doc['doc_number']} {doc['title']}", company_id=doc["company_id"])
    line = current_line(conn, doc_id)
    if line:
        create_notification(conn, line["approver_id"], "결재 요청", doc["title"], f"/erp_doc/{doc_id}")
    conn.commit()
    return JSONResponse({"ok": True})


@router.post("/api/erp_docs/{doc_id}/withdraw")
async def withdraw_erp_doc(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid, uname = u["id"], u["name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    doc, err = get_owned_doc(conn, doc_id, uid)
    if err:
        return err
    # 첫 결재자가 처리하기 전까지만 회수 가능
    acted = conn.execute(
        "SELECT 1 FROM approval_lines WHERE doc_id=? AND step > 0 AND status != 'pending' AND role != '참조'", (doc_id,)
    ).fetchone()
    if doc["status"] not in OPEN or acted:
        return JSONResponse({"error": "결재가 진행된 문서는 철회할 수 없습니다."}, status_code=400)

    conn.execute("UPDATE erp_docs SET status='draft' WHERE id=?", (doc_id,))
    conn.execute(
        "UPDATE approval_lines SET status='pending', comment=NULL, acted_at=NULL WHERE doc_id=?",
        (doc_id,)
    )
    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (doc_id, uid, uname, "철회", "기안자 철회")
    )
    audit.log(conn, uid, "doc_withdraw", "doc", doc_id, f"{doc['doc_number']} {doc['title']}", company_id=doc["company_id"])
    conn.commit()
    return JSONResponse({"ok": True})


@router.get("/api/erp_docs")
async def list_erp_docs(request: Request, doc_type: str = None, u: dict = Depends(require_login), conn = Depends(get_db)):
    user_role = request.session.get("role", "")
    where = ["(doc_type != 'expense' OR company_id = ?)"]
    params = [book_of(conn, u)]
    if user_role != "platform_staff":
        where.append("user_id=?")
        params.append(u["id"])
    if doc_type:
        where.append("doc_type=?")
        params.append(doc_type)
    rows = conn.execute(f"SELECT * FROM erp_docs WHERE {' AND '.join(where)} ORDER BY created_at DESC", params).fetchall()
    return [dict(r) for r in rows]


BOXES = {"wait": "결재대기", "upcoming": "결재예정", "sent": "상신", "draft": "임시보관",
         "done": "완료", "rejected": "반려", "ref": "참조"}
PER_PAGE = 30


@router.get("/approvals", response_class=HTMLResponse)
async def approval_box(request: Request, box: str = "wait", q: str = "", page: int = 1,
                       u: dict = Depends(require_login), conn = Depends(get_db)):
    if box not in BOXES:
        box = "wait"
    uid = u["id"]
    counts = {}
    for k in ("wait", "upcoming", "sent", "draft"):
        sql, args = box_sql(k, uid)
        counts[k] = conn.execute(f"SELECT COUNT(*) FROM erp_docs WHERE {sql}", args).fetchone()[0]

    where, args = box_sql(box, uid)
    if q:
        where += " AND (title LIKE ? OR doc_number LIKE ? OR slip_no LIKE ?)"
        args += [f"%{q}%"] * 3
    total = conn.execute(f"SELECT COUNT(*) FROM erp_docs WHERE {where}", args).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    acting = ",".join("?" * len(ACTING))
    rows = with_status_meta(conn.execute(
        f"""SELECT erp_docs.*,
               (SELECT name FROM users WHERE id = erp_docs.user_id) AS author_name,
               (SELECT us.name FROM approval_lines al JOIN users us ON us.id = al.approver_id
                 WHERE al.doc_id = erp_docs.id AND al.status = 'pending' AND al.role IN ({acting})
                 ORDER BY al.step LIMIT 1) AS cur_name
            FROM erp_docs WHERE {where}
            ORDER BY CASE status WHEN 'urgent' THEN 0 ELSE 1 END, id DESC
            LIMIT {PER_PAGE} OFFSET {(page - 1) * PER_PAGE}""",
        [*ACTING, *args]
    ).fetchall())
    for d in rows:
        d["created_date"] = (d.get("created_at") or "")[:10]
        d["no"] = d.get("doc_number") or d.get("slip_no") or ""
        d["type_label"] = ERP_DOC_TYPE_LABELS.get(d["doc_type"], d["doc_type"])
    return templates.TemplateResponse(request=request, name="erp/approval_box.html", context={
        "request": request, "page_title": "결재 문서함",
        "user_name": u["name"], "docs": rows,
        "box": box, "boxes": BOXES, "counts": counts, "q": q,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/approvals?box={box}&q={q}",
    })


def _preset_forms(conn, book):
    forms = [("draft", "기안서")] + [(dtype, label) for dtype, label in ERP_DOC_TYPES.values()]
    if book:
        forms += [(f"tpl-{r['id']}", r["name"]) for r in conn.execute(
            "SELECT id, name FROM form_templates WHERE company_id=? AND is_active=1 ORDER BY category, name", (book,)
        )]
    return dict(forms)


def _preset_admin(u):
    # 기본 결재선은 고객사 담당자, 원 내부는 스태프가 관리
    return u["role"] in ("client", "platform_staff")


@router.get("/approval-lines", response_class=HTMLResponse)
async def preset_list(request: Request, u: dict = Depends(require_book), conn = Depends(get_db)):
    if not _preset_admin(u):
        return RedirectResponse("/", status_code=303)
    book = u["book"]
    names = {x["id"]: x["name"] for x in books.book_users(conn, book)}
    saved = {r["form_key"]: json.loads(r["lines"]) for r in conn.execute(
        "SELECT form_key, lines FROM approval_presets WHERE company_id=?", (book,)
    )}
    forms = [
        {"key": k, "name": v,
         "summary": " > ".join(f"{p['role']} {names.get(p['user'], '-')}" for p in saved.get(k, []))}
        for k, v in _preset_forms(conn, book).items()
    ]
    return templates.TemplateResponse(request=request, name="erp/approval_preset_list.html", context={
        "request": request, "page_title": "기본 결재선",
        "user_name": u["name"], "forms": forms,
    })


@router.get("/approval-lines/{form_key}", response_class=HTMLResponse)
async def preset_edit(request: Request, form_key: str, u: dict = Depends(require_book), conn = Depends(get_db)):
    forms = _preset_forms(conn, u["book"])
    if not _preset_admin(u) or form_key not in forms:
        return RedirectResponse("/approval-lines", status_code=303)
    return templates.TemplateResponse(request=request, name="erp/approval_preset_form.html", context={
        "request": request, "page_title": f"기본 결재선 - {forms[form_key]}",
        "user_name": u["name"], "form_key": form_key,
        "users": books.book_users(conn, u["book"]),
        "preset": preset_lines(conn, u["book"], form_key),
    })


@router.post("/approval-lines/{form_key}")
async def preset_save(request: Request, form_key: str, u: dict = Depends(require_book), conn = Depends(get_db)):
    book = u["book"]
    if not _preset_admin(u) or form_key not in _preset_forms(conn, book):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    form = await request.form()
    if not any(form.getlist("line_user")):
        conn.execute("DELETE FROM approval_presets WHERE company_id=? AND form_key=?", (book, form_key))
        conn.commit()
        return RedirectResponse("/approval-lines", status_code=303)
    lines, err = parse_lines(form, {x["id"] for x in books.book_users(conn, book)})
    if err:
        return JSONResponse({"error": err}, status_code=400)
    conn.execute(
        """INSERT INTO approval_presets (company_id, form_key, lines, updated_by) VALUES (?,?,?,?)
           ON CONFLICT(company_id, form_key) DO UPDATE SET lines=excluded.lines, updated_by=excluded.updated_by,
           updated_at=datetime('now','localtime')""",
        (book, form_key, json.dumps([{"role": r, "user": i} for r, i in lines], ensure_ascii=False), u["id"])
    )
    conn.commit()
    return RedirectResponse("/approval-lines", status_code=303)
