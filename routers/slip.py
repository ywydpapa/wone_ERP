import csv
import io
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse, StreamingResponse
from core import books
from core.books import require_book
from core.db import with_status_meta
from core.deps import get_db, templates
from core.erp_log import log_activity
from core.tz import now_kst
from core.constants import SIMPLE_SLIP_PURPOSES
from core.export import esc_cell
from core.task_link import stamp_task, task_locked
from routers._helpers import save_upload, insert_approval_lines

router = APIRouter()


def _parse_lines(form, line_count):
    lines = []
    for n in [x.strip() for x in line_count.split(",") if x.strip()]:
        code = form.get(f"account_code_{n}", "").strip()
        if not code:
            continue
        pid = form.get(f"partner_id_{n}", "")
        lines.append({
            "code": code,
            "debit": int(str(form.get(f"debit_{n}", 0) or 0).replace(",", "")),
            "credit": int(str(form.get(f"credit_{n}", 0) or 0).replace(",", "")),
            "partner_id": int(pid) if pid else None,
            "summary": form.get(f"summary_{n}", ""),
            "dept": form.get(f"dept_{n}", ""),
            "project_code": form.get(f"project_{n}", ""),
        })
    return lines


def _get_doc(conn, doc_id, book):
    return conn.execute("SELECT * FROM erp_docs WHERE id=? AND company_id=?", (doc_id, book)).fetchone()


def _book_users(conn, book):
    if book:
        return [dict(r) for r in conn.execute(
            """SELECT id, name, dept, position, role FROM users WHERE id IN (
                   SELECT user_id FROM client_users WHERE company_id=?
                   UNION SELECT user_id FROM employees WHERE company_id=?)
               ORDER BY dept, name""", (book, book)
        )]
    return [dict(r) for r in conn.execute(
        "SELECT id, name, dept, position, role FROM users WHERE role='platform_staff' ORDER BY dept, name"
    )]


def _check_signers(conn, book, reviewer_id, approver_id):
    roles = {x["id"]: x["role"] for x in _book_users(conn, book)}
    if reviewer_id not in roles or roles.get(approver_id) != ("client" if book else "platform_staff"):
        return "검토자 또는 승인자를 확인해 주세요."
    return None


def _valid_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return len(s) == 10


@router.get("/new_slip", response_class=HTMLResponse)
async def new_slip(request: Request, u: dict = Depends(require_book), conn = Depends(get_db)):
    uid = u["id"]
    users = [x for x in _book_users(conn, u["book"]) if x["id"] != uid]
    approvers = [x for x in users if x["role"] == ("client" if u["book"] else "platform_staff")]
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_form.html", context={
            "request": request, "page_title": "전표 입력",
            "user_name": u["name"],
            "users": users,
            "approvers": approvers,
        }
    )


@router.get("/new_slip_simple", response_class=HTMLResponse)
async def new_slip_simple(request: Request, u: dict = Depends(require_book), conn = Depends(get_db)):
    uid = u["id"]
    users = [x for x in _book_users(conn, u["book"]) if x["id"] != uid]
    approvers = [x for x in users if x["role"] == ("client" if u["book"] else "platform_staff")]
    recent_slips = [dict(r) for r in conn.execute(
        """SELECT id, doc_number, title, slip_total, slip_date, status
           FROM erp_docs WHERE user_id=? AND company_id=? AND doc_type='expense' AND slip_type != ''
           ORDER BY id DESC LIMIT 5""", (uid, u["book"])
    ).fetchall()]
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_simple.html", context={
            "request": request, "page_title": "간편 전표 입력",
            "user_name": u["name"],
            "users": users,
            "approvers": approvers,
            "purposes": SIMPLE_SLIP_PURPOSES,
            "recent_slips": recent_slips,
        }
    )


@router.post("/api/slip/simple")
async def create_slip_simple(
    request: Request,
    direction: str = Form(...),
    slip_date: str = Form(""),
    amount: str = Form(""),
    partner_id: str = Form(""),
    purpose: str = Form(""),
    memo: str = Form(""),
    reviewer_id: int = Form(...),
    approver_id: int = Form(...),
    attachment: UploadFile = File(None),
    save_mode: str = Form("submit"),
    u: dict = Depends(require_book),
    conn = Depends(get_db),
):
    uid, uname, book = u["id"], u["name"], u["book"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    if not _valid_date(slip_date):
        return JSONResponse({"error": "전표일자를 확인해 주세요."}, status_code=400)
    err = _check_signers(conn, book, reviewer_id, approver_id)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    try:
        amt = int(amount.replace(",", "")) if amount else 0
        pid = int(partner_id) if partner_id else None
    except ValueError:
        return JSONResponse({"error": "금액 형식이 잘못되었습니다."}, status_code=400)
    if amt <= 0:
        return JSONResponse({"error": "금액을 입력해 주세요."}, status_code=400)
    if books.period_closed(conn, book, slip_date):
        return JSONResponse({"error": "마감된 회계기간입니다."}, status_code=400)

    purpose_info = next((p for p in SIMPLE_SLIP_PURPOSES if p[1] == purpose), None)
    if not purpose_info:
        return JSONResponse({"error": "용도를 선택해 주세요."}, status_code=400)

    purpose_label, account_code, _, _ = purpose_info
    prow = conn.execute("SELECT name FROM partners WHERE id=? AND company_id=?", (pid, book)).fetchone() if pid else None
    pname = prow["name"] if prow else "미지정"

    bank = {"code": "103", "partner_id": None, "summary": ""}
    acct = {"code": account_code, "partner_id": pid, "summary": purpose_label}
    if direction == "지출":
        slip_type = "출금"
        title = f"지출 {amt:,}원 - {purpose_label} / {pname}"
        lines = [{**acct, "debit": amt, "credit": 0}, {**bank, "debit": 0, "credit": amt}]
    else:
        slip_type = "입금"
        title = f"수입 {amt:,}원 - {purpose_label} / {pname}"
        lines = [{**bank, "debit": amt, "credit": 0}, {**acct, "debit": 0, "credit": amt}]

    err = books.check_lines(conn, book, lines)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    saved_name = await save_upload(attachment)
    if isinstance(saved_name, JSONResponse):
        return saved_name

    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    task_id = stamp_task(conn, request, uid, "slip")
    slip_no = books.next_slip_no(conn, book, slip_date)

    new_doc_id = conn.execute(
        """INSERT INTO erp_docs (user_id, doc_type, title, content, attachment, status, dept, slip_type, slip_date,
               slip_total, task_id, company_id, slip_no, doc_number, source_type)
           VALUES (?,'expense',?,?,?,?,'',?,?,?,?,?,?,?,'manual')""",
        (uid, title, memo, saved_name, doc_status, slip_type, slip_date, amt, task_id, book, slip_no, slip_no),
    ).lastrowid
    books.write_lines(conn, new_doc_id, book, lines)

    insert_approval_lines(conn, new_doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, "임시저장" if is_draft else "기안 (간편)")
    log_activity(conn, uid, "create", "slip", new_doc_id, slip_no, f"전표 기안 {slip_no} ({slip_type}, {amt:,}원)")
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
    u: dict = Depends(require_book),
    conn = Depends(get_db),
):
    uid, uname, book = u["id"], u["name"], u["book"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    if not _valid_date(slip_date):
        return JSONResponse({"error": "전표일자를 확인해 주세요."}, status_code=400)
    err = _check_signers(conn, book, reviewer_id, approver_id)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    form = await request.form()
    try:
        lines = _parse_lines(form, line_count)
    except ValueError:
        return JSONResponse({"error": "금액 형식이 잘못되었습니다."}, status_code=400)
    err = books.check_lines(conn, book, lines)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    if books.period_closed(conn, book, slip_date):
        return JSONResponse({"error": "마감된 회계기간입니다."}, status_code=400)

    saved_name = await save_upload(attachment)
    if isinstance(saved_name, JSONResponse):
        return saved_name

    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    task_id = stamp_task(conn, request, uid, "slip")
    slip_no = books.next_slip_no(conn, book, slip_date)
    total = sum(l["debit"] for l in lines)

    new_doc_id = conn.execute(
        """INSERT INTO erp_docs (user_id, doc_type, title, content, attachment, status, dept, slip_type, slip_date,
               slip_total, evidence_type, evidence_no, project_code, task_id, company_id, slip_no, doc_number, source_type)
           VALUES (?,'expense',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'manual')""",
        (uid, title, content, saved_name, doc_status, dept, slip_type, slip_date, total,
         evidence_type, evidence_no, project_code, task_id, book, slip_no, slip_no),
    ).lastrowid
    books.write_lines(conn, new_doc_id, book, lines)

    insert_approval_lines(conn, new_doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, "임시저장" if is_draft else "기안")
    log_activity(conn, uid, "create", "slip", new_doc_id, slip_no, f"전표 기안 {slip_no} ({slip_type})")
    conn.commit()
    return RedirectResponse(url=f"/erp_doc/{new_doc_id}?created=1", status_code=303)


@router.get("/api/accounts")
async def api_accounts(request: Request, u: dict = Depends(require_book), conn = Depends(get_db)):
    rows = conn.execute(
        """SELECT code, name, category, is_debit, req_partner, req_dept FROM accounts
           WHERE company_id=? AND is_active=1 ORDER BY code""", (u["book"],)
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/partners")
async def api_partners(request: Request, u: dict = Depends(require_book), conn = Depends(get_db)):
    rows = conn.execute(
        """SELECT id, code, name, biz_no, representative, biz_type, biz_item FROM partners
           WHERE company_id=? AND is_active=1 ORDER BY code""", (u["book"],)
    ).fetchall()
    return [dict(r) for r in rows]


def _slip_filters(request, uid, user_role, book):
    q = request.query_params.get("q", "").strip()
    slip_type = request.query_params.get("slip_type", "")
    status = request.query_params.get("status", "")
    date_from = request.query_params.get("date_from", "")
    date_to = request.query_params.get("date_to", "")
    author_id = request.query_params.get("author_id", "")

    where = ["e.doc_type='expense'", "e.slip_type != ''", "e.company_id=?"]
    params = [book]

    if user_role not in ("platform_staff", "client"):
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
    if author_id.isdigit():
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
async def slip_list(request: Request, u: dict = Depends(require_book), conn = Depends(get_db)):
    user_role = request.session.get("role", "")
    uid = u["id"]
    page = request.query_params.get("page", "1")
    page = max(1, int(page)) if page.isdigit() else 1
    per_page = 20

    where_sql, params, filters = _slip_filters(request, uid, user_role, u["book"])

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
            "SELECT DISTINCT u.id, u.name FROM erp_docs e JOIN users u ON e.user_id=u.id WHERE e.doc_type='expense' AND e.slip_type != '' AND e.company_id=? ORDER BY u.name",
            (u["book"],)
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
async def slip_list_excel(request: Request, u: dict = Depends(require_book), conn = Depends(get_db)):
    user_role = request.session.get("role", "")
    uid = u["id"]
    where_sql, params, _ = _slip_filters(request, uid, user_role, u["book"])

    STATUS_LABELS = {"draft": "임시저장", "wait": "대기", "progress": "진행중", "done": "완료", "rejected": "반려", "approved": "승인"}

    rows = conn.execute(
        f"""SELECT e.doc_number, e.slip_no, e.slip_date, e.slip_type, e.title,
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
            r["slip_no"] or r["doc_number"] or "", r["slip_date"] or "", r["slip_type"] or "",
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
async def edit_slip(request: Request, doc_id: int, u: dict = Depends(require_book), conn = Depends(get_db)):
    uid = u["id"]
    doc = _get_doc(conn, doc_id, u["book"])
    if not doc:
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
    if doc["user_id"] != uid:
        return HTMLResponse("<h2>본인 문서만 수정할 수 있습니다</h2>", status_code=403)
    if doc["status"] not in ("draft", "rejected"):
        return HTMLResponse("<h2>임시저장 또는 반려 상태의 문서만 수정할 수 있습니다</h2>", status_code=400)
    slip_lines_rows = [dict(s) for s in conn.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]
    users = [x for x in _book_users(conn, u["book"]) if x["id"] != uid]
    approvers = [x for x in users if x["role"] == ("client" if u["book"] else "platform_staff")]
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
            "approvers": approvers,
            "edit_mode": True, "doc": doc,
            "slip_lines": slip_lines_rows,
            "reviewer_id": reviewer_id, "approver_id": approver_id,
        }
    )


@router.get("/copy_slip/{doc_id}", response_class=HTMLResponse)
async def copy_slip(request: Request, doc_id: int, u: dict = Depends(require_book), conn = Depends(get_db)):
    uid = u["id"]
    doc = _get_doc(conn, doc_id, u["book"])
    if not doc:
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
    slip_lines_rows = [dict(s) for s in conn.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]
    users = [x for x in _book_users(conn, u["book"]) if x["id"] != uid]
    approvers = [x for x in users if x["role"] == ("client" if u["book"] else "platform_staff")]
    doc = dict(doc)
    doc["title"] = "[복사] " + doc["title"]
    doc["slip_date"] = now_kst().strftime("%Y-%m-%d")
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_form.html", context={
            "request": request, "page_title": "전표 복사",
            "user_name": u["name"],
            "users": users,
            "approvers": approvers,
            "edit_mode": False, "copy_mode": True,
            "doc": doc,
            "slip_lines": slip_lines_rows,
        }
    )


@router.post("/api/slip/{doc_id}/reverse")
async def reverse_slip(doc_id: int, slip_date: str = Form(...), u: dict = Depends(require_book), conn = Depends(get_db)):
    if not _get_doc(conn, doc_id, u["book"]):
        return JSONResponse({"error": "문서를 찾을 수 없습니다."}, status_code=404)
    if u["role"] not in ("client", "platform_staff"):
        return JSONResponse({"error": "역분개 권한이 없습니다."}, status_code=403)
    if not _valid_date(slip_date):
        return JSONResponse({"error": "전표일자를 확인해 주세요."}, status_code=400)
    if conn.execute("SELECT 1 FROM tax_invoices WHERE doc_id=? AND company_id=?", (doc_id, u["book"])).fetchone():
        return JSONResponse({"error": "세금계산서가 연결된 전표는 세금계산서 수정발행으로 정정해 주세요."}, status_code=400)
    try:
        new_id = books.reverse(conn, doc_id, u["id"], slip_date)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return JSONResponse({"ok": True, "doc_id": new_id})


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
    u: dict = Depends(require_book),
    conn = Depends(get_db),
):
    uid, uname, book = u["id"], u["name"], u["book"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    doc = _get_doc(conn, doc_id, book)
    if not doc:
        return JSONResponse({"error": "문서를 찾을 수 없습니다."}, status_code=404)
    if doc["user_id"] != uid or doc["status"] not in ("draft", "rejected"):
        return JSONResponse({"error": "수정할 수 없는 문서입니다."}, status_code=400)
    if task_locked(conn, doc["task_id"]):
        return JSONResponse({"error": "승인된 태스크의 전표는 수정할 수 없습니다"}, status_code=403)
    if not _valid_date(slip_date):
        return JSONResponse({"error": "전표일자를 확인해 주세요."}, status_code=400)
    err = _check_signers(conn, book, reviewer_id, approver_id)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    if books.period_closed(conn, book, slip_date):
        return JSONResponse({"error": "마감된 회계기간입니다."}, status_code=400)
    form = await request.form()
    try:
        lines = _parse_lines(form, line_count)
    except ValueError:
        return JSONResponse({"error": "금액 형식이 잘못되었습니다."}, status_code=400)
    err = books.check_lines(conn, book, lines)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    result = await save_upload(attachment)
    if isinstance(result, JSONResponse):
        return result
    saved_name = result if result else (doc["attachment"] or "")

    slip_no = doc["slip_no"]
    if slip_date != doc["slip_date"] or not slip_no:
        slip_no = books.next_slip_no(conn, book, slip_date)

    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    conn.execute(
        """UPDATE erp_docs SET title=?, content=?, slip_type=?, slip_date=?, dept=?, slip_total=?, attachment=?, status=?,
               evidence_type=?, evidence_no=?, project_code=?, slip_no=?, doc_number=? WHERE id=?""",
        (title, content, slip_type, slip_date, dept, sum(l["debit"] for l in lines), saved_name, doc_status,
         evidence_type, evidence_no, project_code, slip_no, slip_no, doc_id)
    )
    books.write_lines(conn, doc_id, book, lines)
    conn.execute("DELETE FROM approval_lines WHERE doc_id=?", (doc_id,))
    insert_approval_lines(conn, doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, "수정")
    log_activity(conn, uid, "update", "slip", doc_id, slip_no, f"전표 수정 {slip_no}")
    conn.commit()
    return RedirectResponse(url=f"/erp_doc/{doc_id}?created=1", status_code=303)


@router.post("/api/slip/{doc_id}/delete")
async def delete_slip(request: Request, doc_id: int, u: dict = Depends(require_book), conn = Depends(get_db)):
    uid = u["id"]
    doc = _get_doc(conn, doc_id, u["book"])
    if not doc:
        return JSONResponse({"error": "문서를 찾을 수 없습니다."}, status_code=404)
    if doc["user_id"] != uid:
        return JSONResponse({"error": "기안자만 수행할 수 있습니다."}, status_code=403)
    if task_locked(conn, doc["task_id"]):
        return JSONResponse({"error": "승인된 태스크의 전표는 삭제할 수 없습니다"}, status_code=403)
    if doc["status"] not in ("draft", "rejected"):
        return JSONResponse({"error": "임시저장 또는 반려 상태의 문서만 삭제할 수 있습니다."}, status_code=400)
    if books.period_closed(conn, u["book"], doc["slip_date"]):
        return JSONResponse({"error": "마감된 회계기간입니다."}, status_code=400)
    conn.execute("DELETE FROM slip_lines WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM approval_lines WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM doc_history WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM erp_docs WHERE id=?", (doc_id,))
    log_activity(conn, uid, "delete", "slip", doc_id, doc["doc_number"], f"전표 삭제 {doc['doc_number']}")
    conn.commit()
    return JSONResponse({"ok": True})


@router.get("/erp_doc/{doc_id}/trade_statement", response_class=HTMLResponse)
async def trade_statement(request: Request, doc_id: int, u: dict = Depends(require_book), conn = Depends(get_db)):
    doc = _get_doc(conn, doc_id, u["book"])
    if not doc:
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
    inv = conn.execute("SELECT * FROM tax_invoices WHERE doc_id=? AND company_id=?", (doc_id, u["book"])).fetchone()
    pid = None
    if inv:
        pid = inv["partner_id"]
        lines = [{"line_no": it["line_no"], "item_code": "", "item_name": it["name"], "unit": it["spec"] or "",
                  "quantity": it["qty"], "unit_price": it["unit_price"], "amount": it["supply_amt"]}
                 for it in conn.execute("SELECT * FROM tax_invoice_items WHERE invoice_id=? ORDER BY line_no", (inv["id"],))]
        total, tax = inv["supply_amt"], inv["vat"]
    else:
        lines = []
        for sl in conn.execute("SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)):
            amt = sl["debit"] or sl["credit"] or 0
            pid = pid or sl["partner_id"]
            lines.append({"line_no": sl["line_no"], "item_code": sl["account_code"] or "",
                          "item_name": sl["summary"] or sl["account_name"] or "", "unit": "",
                          "quantity": 1, "unit_price": amt, "amount": amt})
        total = doc["slip_total"] or 0
        tax = int(total * 0.1)
    partner = {"name": "", "biz_no": "", "representative": "", "address": ""}
    if pid:
        p = conn.execute(
            "SELECT name, biz_no, representative, address, biz_type, biz_item FROM partners WHERE id=? AND company_id=?",
            (pid, u["book"]),
        ).fetchone()
        if p:
            partner = dict(p)
    company = books.company_info(conn, u["book"])
    doc_type, supplier, buyer = "sales", company, partner
    if inv and inv["kind"] == "매입":
        doc_type, supplier, buyer = "purchase", partner, company
    return templates.TemplateResponse(request=request, name="erp/trade_statement.html", context={
        "request": request, "doc_type": doc_type,
        "doc_number": doc["slip_no"] or doc["doc_number"] or "", "doc_date": doc["slip_date"] or "",
        "supplier": supplier, "buyer": buyer, "lines": lines,
        "total_amount": total, "tax_amount": tax,
    })


@router.get("/erp_doc/{doc_id}/receipt", response_class=HTMLResponse)
async def receipt(request: Request, doc_id: int, u: dict = Depends(require_book), conn = Depends(get_db)):
    doc = conn.execute(
        "SELECT e.*, u.name as author_name FROM erp_docs e LEFT JOIN users u ON e.user_id=u.id WHERE e.id=? AND e.company_id=?",
        (doc_id, u["book"])
    ).fetchone()
    if not doc:
        return HTMLResponse("<h2>문서를 찾을 수 없습니다</h2>", status_code=404)
    slip_lines_data = [dict(s) for s in conn.execute(
        "SELECT * FROM slip_lines WHERE doc_id=? ORDER BY line_no", (doc_id,)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/receipt.html", context={
        "request": request, "doc": dict(doc), "slip_lines": slip_lines_data,
        "company": books.company_info(conn, u["book"]),
    })


@router.get("/erp_doc/{doc_id}/tax_invoice", response_class=HTMLResponse)
async def tax_invoice(request: Request, doc_id: int, u: dict = Depends(require_book), conn = Depends(get_db)):
    row = conn.execute(
        "SELECT id FROM tax_invoices WHERE doc_id=? AND company_id=?", (doc_id, u["book"])
    ).fetchone()
    if not row:
        return HTMLResponse("<h2>세금계산서가 없는 전표입니다</h2>", status_code=404)
    return RedirectResponse(f"/tax-invoices/{row['id']}/print", status_code=303)
