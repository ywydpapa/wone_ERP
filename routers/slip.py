import csv
import io
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse, StreamingResponse
from core.db import with_status_meta
from core.deps import get_db, require_login, templates
from core.erp_log import log_activity
from core.tz import now_kst
from core.constants import SIMPLE_SLIP_PURPOSES, COMPANY_INFO
from core.export import esc_cell
from core.task_link import stamp_task, task_locked
from routers._helpers import save_upload, insert_approval_lines, get_owned_doc

router = APIRouter()


def _check_period_closed(conn, slip_date):
    if not slip_date or len(slip_date) < 7:
        return False
    y, m = int(slip_date[:4]), int(slip_date[5:7])
    row = conn.execute(
        "SELECT status FROM fi_closings WHERE year=? AND month=? AND status='closed'", [y, m]
    ).fetchone()
    return bool(row)


def _parse_slip_lines(form, line_count):
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
    return lines, total_debit, total_credit


@router.get("/new_slip", response_class=HTMLResponse)
async def new_slip(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    users = [dict(r) for r in conn.execute(
        "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
    ).fetchall()]
    year = now_kst().year
    last_id = conn.execute(
        "SELECT MAX(id) FROM erp_docs WHERE doc_type='expense'"
    ).fetchone()[0] or 0
    next_doc_number = f"EXP-{year}-{last_id + 1:04d}"
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_form.html", context={
            "request": request, "page_title": "전표 입력",
            "user_name": u["name"],
            "users": users,
            "next_doc_number": next_doc_number,
        }
    )


@router.get("/new_slip_simple", response_class=HTMLResponse)
async def new_slip_simple(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    users = [dict(r) for r in conn.execute(
        "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
    ).fetchall()]
    recent_partners = [r[0] for r in conn.execute(
        "SELECT DISTINCT partner FROM slip_lines WHERE partner != '' ORDER BY id DESC LIMIT 20"
    ).fetchall()]
    recent_slips = [dict(r) for r in conn.execute(
        """SELECT id, doc_number, title, slip_total, slip_date, status
           FROM erp_docs WHERE user_id=? AND doc_type='expense' AND slip_type != ''
           ORDER BY id DESC LIMIT 5""", (uid,)
    ).fetchall()]
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_simple.html", context={
            "request": request, "page_title": "간편 전표 입력",
            "user_name": u["name"],
            "users": users,
            "purposes": SIMPLE_SLIP_PURPOSES,
            "recent_partners": recent_partners,
            "recent_slips": recent_slips,
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
    attachment: UploadFile = File(None),
    save_mode: str = Form("submit"),
    u: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = u["id"]
    uname = u["name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    amt = int(amount.replace(",", "")) if amount else 0
    if amt <= 0:
        return JSONResponse({"error": "금액을 입력해 주세요."}, status_code=400)
    if _check_period_closed(conn, slip_date):
        return JSONResponse({"error": "마감된 기간에는 전표를 등록할 수 없습니다."}, status_code=400)

    purpose_info = next((p for p in SIMPLE_SLIP_PURPOSES if p[1] == purpose), None)
    if not purpose_info:
        return JSONResponse({"error": "용도를 선택해 주세요."}, status_code=400)

    purpose_label, account_code, account_name, is_expense = purpose_info

    if direction == "지출":
        slip_type = "출금"
        title = f"지출 {amt:,}원 - {purpose_label} / {partner or '미지정'}"
        lines = [
            (1, f"[{account_code}] {account_name}", account_code, amt, 0, partner, purpose_label),
            (2, "[103] 보통예금", "103", 0, amt, "", ""),
        ]
    else:
        slip_type = "입금"
        title = f"수입 {amt:,}원 - {purpose_label} / {partner or '미지정'}"
        lines = [
            (1, "[103] 보통예금", "103", amt, 0, "", ""),
            (2, f"[{account_code}] {account_name}", account_code, 0, amt, partner, purpose_label),
        ]

    saved_name = await save_upload(attachment)
    if isinstance(saved_name, JSONResponse):
        return saved_name

    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    year = now_kst().year
    task_id = stamp_task(conn, request, uid, "slip")

    cur = conn.execute(
        "INSERT INTO erp_docs (user_id, doc_type, title, content, attachment, status, dept, slip_type, slip_date, slip_total, task_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (uid, "expense", title, memo, saved_name, doc_status, "", slip_type, slip_date, amt, task_id),
    )
    new_doc_id = cur.lastrowid
    doc_number = f"EXP-{year}-{new_doc_id:04d}"
    conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, new_doc_id))

    for line_no, account, ac_code, debit, credit, ptr, summary in lines:
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
            (new_doc_id, line_no, account, ac_code, debit, credit, ptr, summary)
        )

    insert_approval_lines(conn, new_doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, "임시저장" if is_draft else "기안 (간편)")
    log_activity(conn, uid, "create", "slip", new_doc_id, doc_number, f"전표 기안 {doc_number} ({slip_type}, {amt:,}원)")
    conn.commit()
    return RedirectResponse(url=f"/erp_doc/{new_doc_id}?created=1", status_code=303)


@router.post("/api/slip")
async def create_slip(
    request: Request,
    title: str = Form(""), content: str = Form(""),
    slip_type: str = Form(""), slip_date: str = Form(""),
    dept: str = Form(""),
    evidence_type: str = Form(""), evidence_no: str = Form(""), project_code: str = Form(""),
    reviewer_id: int = Form(...),
    approver_id: int = Form(...),
    line_count: str = Form(""),
    attachment: UploadFile = File(None),
    save_mode: str = Form("submit"),
    u: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = u["id"]
    uname = u["name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    form = await request.form()
    lines, total_debit, total_credit = _parse_slip_lines(form, line_count)
    if total_debit != total_credit:
        return JSONResponse({"error": "차변과 대변 합계가 일치하지 않습니다."}, status_code=400)
    if _check_period_closed(conn, slip_date):
        return JSONResponse({"error": "마감된 기간에는 전표를 등록할 수 없습니다."}, status_code=400)

    saved_name = await save_upload(attachment)
    if isinstance(saved_name, JSONResponse):
        return saved_name

    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    year = now_kst().year
    task_id = stamp_task(conn, request, uid, "slip")

    cur = conn.execute(
        "INSERT INTO erp_docs (user_id, doc_type, title, content, attachment, status, dept, slip_type, slip_date, slip_total, evidence_type, evidence_no, project_code, task_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, "expense", title, content, saved_name, doc_status, dept, slip_type, slip_date, total_debit, evidence_type, evidence_no, project_code, task_id),
    )
    new_doc_id = cur.lastrowid
    doc_number = f"EXP-{year}-{new_doc_id:04d}"
    conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, new_doc_id))

    for line_no, account, account_code, debit, credit, partner, summary in lines:
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
            (new_doc_id, line_no, account, account_code, debit, credit, partner, summary)
        )

    insert_approval_lines(conn, new_doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, "임시저장" if is_draft else "기안")
    log_activity(conn, uid, "create", "slip", new_doc_id, doc_number, f"전표 기안 {doc_number} ({slip_type})")
    conn.commit()
    return RedirectResponse(url=f"/erp_doc/{new_doc_id}?created=1", status_code=303)


@router.get("/api/accounts")
async def api_accounts(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    rows = conn.execute(
        "SELECT code, name, category, is_debit FROM accounts WHERE is_active=1 ORDER BY code"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/partners")
async def api_partners(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    rows = conn.execute(
        "SELECT code, name, biz_no, representative, biz_type, biz_item FROM partners WHERE is_active=1 ORDER BY code"
    ).fetchall()
    return [dict(r) for r in rows]


def _slip_filters(request, uid, user_role):
    q = request.query_params.get("q", "").strip()
    slip_type = request.query_params.get("slip_type", "")
    status = request.query_params.get("status", "")
    date_from = request.query_params.get("date_from", "")
    date_to = request.query_params.get("date_to", "")
    author_id = request.query_params.get("author_id", "")

    where = ["e.doc_type='expense'", "e.slip_type != ''"]
    params = []

    if user_role != "platform_staff":
        where.append("e.user_id=?")
        params.append(uid)
    if slip_type:
        where.append("e.slip_type=?")
        params.append(slip_type)
    if status:
        where.append("e.status=?")
        params.append(status)
    if date_from:
        where.append("e.slip_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("e.slip_date <= ?")
        params.append(date_to)
    if author_id:
        where.append("e.user_id=?")
        params.append(int(author_id))
    if q:
        where.append("""(e.title LIKE ? OR e.doc_number LIKE ? OR EXISTS (
            SELECT 1 FROM slip_lines sl WHERE sl.doc_id=e.id AND sl.partner LIKE ?
        ))""")
        like = f"%{q}%"
        params += [like, like, like]

    filters = {"q": q, "slip_type": slip_type, "status": status,
               "date_from": date_from, "date_to": date_to, "author_id": author_id}
    return " AND ".join(where), params, filters


@router.get("/slip_list", response_class=HTMLResponse)
async def slip_list(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    user_role = request.session.get("role", "")
    uid = u["id"]
    page = int(request.query_params.get("page", 1))
    per_page = 20

    where_sql, params, filters = _slip_filters(request, uid, user_role)

    total_row = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(e.slip_total), 0) FROM erp_docs e WHERE {where_sql}",
        params
    ).fetchone()
    total_count = total_row[0]
    total_amount = total_row[1]
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    docs = with_status_meta(conn.execute(
        f"""SELECT e.*, u.name as author_name
            FROM erp_docs e
            LEFT JOIN users u ON e.user_id = u.id
            WHERE {where_sql}
            ORDER BY e.id DESC LIMIT ? OFFSET ?""",
        params + [per_page, (page - 1) * per_page]
    ).fetchall())

    for d in docs:
        d['display_date'] = d.get('slip_date') or (d['created_at'][:10] if d.get('created_at') else '')

    qs_parts = []
    for k, v in filters.items():
        if v:
            qs_parts.append(f"{k}={v}")
    filter_qs = "&".join(qs_parts) if qs_parts else ""
    base_url = "/slip_list?" + filter_qs

    authors = []
    if user_role == "platform_staff":
        authors = [dict(r) for r in conn.execute(
            "SELECT DISTINCT u.id, u.name FROM erp_docs e JOIN users u ON e.user_id=u.id WHERE e.doc_type='expense' AND e.slip_type != '' ORDER BY u.name"
        ).fetchall()]

    return templates.TemplateResponse(request=request, name="erp/slip_list.html", context={
        "request": request, "page_title": "전표 조회",
        "user_name": u["name"],
        "docs": docs,
        "authors": authors,
        "page": page, "total_pages": total_pages,
        "total_count": total_count, "total_amount": total_amount,
        "base_url": base_url, "filter_qs": filter_qs,
        **filters,
    })


@router.get("/slip_list/excel")
async def slip_list_excel(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    user_role = request.session.get("role", "")
    uid = u["id"]
    where_sql, params, _ = _slip_filters(request, uid, user_role)

    STATUS_LABELS = {"draft": "임시저장", "wait": "대기", "progress": "진행중", "done": "완료", "rejected": "반려", "approved": "승인"}

    rows = conn.execute(
        f"""SELECT e.doc_number, e.slip_date, e.slip_type, e.title,
                   e.slip_total, u.name as author_name, e.status
            FROM erp_docs e
            LEFT JOIN users u ON e.user_id = u.id
            WHERE {where_sql}
            ORDER BY e.id DESC""",
        params
    ).fetchall()

    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(["전표번호", "전표일자", "유형", "제목", "금액", "기안자", "상태"])
    for r in rows:
        writer.writerow([esc_cell(v) for v in [
            r["doc_number"] or "", r["slip_date"] or "", r["slip_type"] or "",
            r["title"] or "", r["slip_total"] or 0, r["author_name"] or "",
            STATUS_LABELS.get(r["status"], r["status"] or ""),
        ]])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=slip_list.csv"},
    )


@router.get("/edit_slip/{doc_id}", response_class=HTMLResponse)
async def edit_slip(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
    if doc["user_id"] != uid:
        return HTMLResponse("<h2>본인 문서만 수정할 수 있습니다</h2>", status_code=403)
    if doc["status"] not in ("draft", "rejected"):
        return HTMLResponse("<h2>임시저장 또는 반려 상태의 문서만 수정할 수 있습니다</h2>", status_code=400)
    slip_lines_rows = [dict(s) for s in conn.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]
    users = [dict(r) for r in conn.execute(
        "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
    ).fetchall()]
    approval = [dict(a) for a in conn.execute(
        "SELECT * FROM approval_lines WHERE doc_id=? ORDER BY step", (doc_id,)
    ).fetchall()]
    doc = dict(doc)
    reviewer_id = next((a["approver_id"] for a in approval if a["role"] == "검토"), "")
    approver_id = next((a["approver_id"] for a in approval if a["role"] == "승인"), "")
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_form.html", context={
            "request": request, "page_title": "전표 수정",
            "user_name": u["name"],
            "users": users,
            "edit_mode": True, "doc": doc,
            "slip_lines": slip_lines_rows,
            "reviewer_id": reviewer_id, "approver_id": approver_id,
        }
    )


@router.get("/copy_slip/{doc_id}", response_class=HTMLResponse)
async def copy_slip(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
    slip_lines_rows = [dict(s) for s in conn.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]
    users = [dict(r) for r in conn.execute(
        "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
    ).fetchall()]
    doc = dict(doc)
    doc["title"] = "[복사] " + doc["title"]
    doc["slip_date"] = now_kst().strftime("%Y-%m-%d")
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_form.html", context={
            "request": request, "page_title": "전표 복사",
            "user_name": u["name"],
            "users": users,
            "edit_mode": False, "copy_mode": True,
            "doc": doc,
            "slip_lines": slip_lines_rows,
        }
    )


@router.get("/reverse_slip/{doc_id}", response_class=HTMLResponse)
async def reverse_slip(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
    slip_lines_rows = [dict(s) for s in conn.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]
    for line in slip_lines_rows:
        line["debit"], line["credit"] = line["credit"], line["debit"]
    users = [dict(r) for r in conn.execute(
        "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
    ).fetchall()]
    doc = dict(doc)
    doc["title"] = "[역분개] " + doc["title"]
    doc["slip_date"] = now_kst().strftime("%Y-%m-%d")
    slip_type_map = {"입금": "출금", "출금": "입금"}
    doc["slip_type"] = slip_type_map.get(doc["slip_type"], doc["slip_type"])
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_form.html", context={
            "request": request, "page_title": "역분개",
            "user_name": u["name"],
            "users": users,
            "edit_mode": False, "reverse_mode": True,
            "doc": doc,
            "slip_lines": slip_lines_rows,
        }
    )


@router.post("/api/slip/{doc_id}")
async def update_slip(
    request: Request, doc_id: int,
    title: str = Form(""), content: str = Form(""),
    slip_type: str = Form(""), slip_date: str = Form(""),
    dept: str = Form(""),
    evidence_type: str = Form(""), evidence_no: str = Form(""), project_code: str = Form(""),
    reviewer_id: int = Form(...),
    approver_id: int = Form(...),
    line_count: str = Form(""),
    attachment: UploadFile = File(None),
    save_mode: str = Form("submit"),
    u: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = u["id"]
    uname = u["name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
    if not doc or doc["user_id"] != uid or doc["status"] not in ("draft", "rejected"):
        return JSONResponse({"error": "수정할 수 없는 문서입니다."}, status_code=400)
    if task_locked(conn, doc["task_id"]):
        return JSONResponse({"error": "승인된 태스크의 전표는 수정할 수 없습니다"}, status_code=403)
    if _check_period_closed(conn, slip_date):
        return JSONResponse({"error": "마감된 기간에는 전표를 수정할 수 없습니다."}, status_code=400)
    form = await request.form()
    lines, total_debit, total_credit = _parse_slip_lines(form, line_count)
    if total_debit != total_credit:
        return JSONResponse({"error": "차변과 대변 합계가 일치하지 않습니다."}, status_code=400)

    result = await save_upload(attachment)
    if isinstance(result, JSONResponse):
        return result
    saved_name = result if result else (doc["attachment"] or "")

    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    conn.execute(
        "UPDATE erp_docs SET title=?, content=?, slip_type=?, slip_date=?, dept=?, slip_total=?, attachment=?, status=?, evidence_type=?, evidence_no=?, project_code=? WHERE id=?",
        (title, content, slip_type, slip_date, dept, total_debit, saved_name, doc_status, evidence_type, evidence_no, project_code, doc_id)
    )
    conn.execute("DELETE FROM slip_lines WHERE doc_id=?", (doc_id,))
    for line_no, account, account_code, debit, credit, partner, summary in lines:
        conn.execute(
            "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, line_no, account, account_code, debit, credit, partner, summary)
        )
    conn.execute("DELETE FROM approval_lines WHERE doc_id=?", (doc_id,))
    insert_approval_lines(conn, doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, "수정")
    doc_row = conn.execute("SELECT doc_number FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
    log_activity(conn, u["id"], "update", "slip", doc_id, doc_row["doc_number"], f"전표 수정 {doc_row['doc_number']}")
    conn.commit()
    return RedirectResponse(url=f"/erp_doc/{doc_id}?created=1", status_code=303)


@router.post("/api/slip/{doc_id}/delete")
async def delete_slip(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["id"]
    doc, err = get_owned_doc(conn, doc_id, uid)
    if err:
        return err
    if task_locked(conn, doc["task_id"]):
        return JSONResponse({"error": "승인된 태스크의 전표는 삭제할 수 없습니다"}, status_code=403)
    if doc["status"] not in ("draft", "rejected"):
        return JSONResponse({"error": "임시저장 또는 반려 상태의 문서만 삭제할 수 있습니다."}, status_code=400)
    if _check_period_closed(conn, doc.get("slip_date", "")):
        return JSONResponse({"error": "마감된 기간의 전표는 삭제할 수 없습니다."}, status_code=400)
    doc_row = conn.execute("SELECT doc_number FROM erp_docs WHERE id=?", (doc_id,)).fetchone()
    conn.execute("DELETE FROM slip_lines WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM approval_lines WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM doc_history WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM erp_docs WHERE id=?", (doc_id,))
    log_activity(conn, u["id"], "delete", "slip", doc_id, doc_row["doc_number"], f"전표 삭제 {doc_row['doc_number']}")
    conn.commit()
    return JSONResponse({"ok": True})


@router.get("/erp_doc/{doc_id}/trade_statement", response_class=HTMLResponse)
async def trade_statement(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    doc = conn.execute(
        "SELECT e.*, u.name as author_name FROM erp_docs e LEFT JOIN users u ON e.user_id=u.id WHERE e.id=?",
        (doc_id,)
    ).fetchone()
    if not doc:
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
    slip_lines_data = [dict(s) for s in conn.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]
    doc_dict = dict(doc)
    doc_dict['created_date'] = doc_dict['created_at'][:10] if doc_dict.get('created_at') else ''
    partner_name = slip_lines_data[0]['partner'] if slip_lines_data else '-'
    total_supply = doc_dict.get('slip_total') or 0
    total_tax = int(total_supply * 0.1)
    for sl in slip_lines_data:
        amt = sl['debit'] if sl.get('debit', 0) > 0 else sl.get('credit', 0)
        sl['amount'] = amt
        sl['tax'] = int(amt * 0.1)
    return templates.TemplateResponse(request=request, name="erp/trade_statement.html", context={
        "request": request, "doc": doc_dict, "slip_lines": slip_lines_data,
        "partner_name": partner_name, "total_supply": total_supply, "total_tax": total_tax,
        "company": COMPANY_INFO,
    })


@router.get("/erp_doc/{doc_id}/receipt", response_class=HTMLResponse)
async def receipt(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    doc = conn.execute(
        "SELECT e.*, u.name as author_name FROM erp_docs e LEFT JOIN users u ON e.user_id=u.id WHERE e.id=?",
        (doc_id,)
    ).fetchone()
    if not doc:
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
    slip_lines_data = [dict(s) for s in conn.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/receipt.html", context={
        "request": request, "doc": dict(doc), "slip_lines": slip_lines_data,
        "company": COMPANY_INFO,
    })


@router.get("/erp_doc/{doc_id}/tax_invoice", response_class=HTMLResponse)
async def tax_invoice(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    doc = conn.execute(
        "SELECT e.*, u.name as author_name FROM erp_docs e LEFT JOIN users u ON e.user_id=u.id WHERE e.id=?",
        (doc_id,)
    ).fetchone()
    if not doc:
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
    slip_lines_data = [dict(s) for s in conn.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]
    doc_dict = dict(doc)
    doc_dict['created_date'] = doc_dict['created_at'][:10] if doc_dict.get('created_at') else ''
    partner_name = slip_lines_data[0]['partner'] if slip_lines_data else ''
    slip_md = doc_dict['slip_date'][5:10] if doc_dict.get('slip_date') else (doc_dict['created_at'][5:10] if doc_dict.get('created_at') else '')

    partner_info = {"name": partner_name, "biz_no": "", "representative": "", "address": "", "biz_type": "", "biz_item": ""}
    if partner_name:
        p = conn.execute(
            "SELECT name, biz_no, representative, address, biz_type, biz_item FROM partners WHERE name=?",
            (partner_name,),
        ).fetchone()
        if p:
            partner_info = dict(p)

    slip_total = doc_dict.get('slip_total', 0) or 0
    total_tax = int(slip_total * 0.1)
    for sl in slip_lines_data:
        amt = sl['debit'] if sl.get('debit', 0) > 0 else sl.get('credit', 0)
        sl['amount'] = amt
        sl['tax'] = int(amt * 0.1)
    return templates.TemplateResponse(request=request, name="erp/tax_invoice.html", context={
        "request": request, "doc": doc_dict, "slip_lines": slip_lines_data,
        "partner_name": partner_info.get("name", ""), "partner": partner_info,
        "slip_md": slip_md, "slip_total": slip_total, "total_tax": total_tax,
        "company": COMPANY_INFO,
    })
