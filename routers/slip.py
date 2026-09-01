from typing import Optional
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.db import with_status_meta
from core.deps import get_db, require_login, templates
from core.tz import now_kst
from core.constants import SIMPLE_SLIP_PURPOSES
from routers._helpers import save_upload, insert_approval_lines

router = APIRouter()


@router.get("/new_slip", response_class=HTMLResponse)
async def new_slip(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    users = [dict(r) for r in conn.execute(
        "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
    ).fetchall()]
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_form.html", context={
            "request": request, "page_title": "전표 입력",
            "user_name": u["user_name"],
            "users": users,
        }
    )


@router.get("/new_slip_simple", response_class=HTMLResponse)
async def new_slip_simple(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    users = [dict(r) for r in conn.execute(
        "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
    ).fetchall()]
    recent_partners = [r[0] for r in conn.execute(
        "SELECT DISTINCT partner FROM slip_lines WHERE partner != '' ORDER BY id DESC LIMIT 20"
    ).fetchall()]
    return templates.TemplateResponse(
        request=request, name="erp/erp_slip_simple.html", context={
            "request": request, "page_title": "간편 전표 입력",
            "user_name": u["user_name"],
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
    u: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = u["user_id"]
    uname = u["user_name"]
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

    saved_name = await save_upload(attachment)
    if isinstance(saved_name, JSONResponse):
        return saved_name

    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    year = now_kst().year

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

    insert_approval_lines(conn, new_doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, "임시저장" if is_draft else "기안 (간편)")
    conn.commit()
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
    u: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = u["user_id"]
    uname = u["user_name"]
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

    saved_name = await save_upload(attachment)
    if isinstance(saved_name, JSONResponse):
        return saved_name

    is_draft = (save_mode == "draft")
    doc_status = "draft" if is_draft else "wait"
    year = now_kst().year

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

    insert_approval_lines(conn, new_doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, "임시저장" if is_draft else "기안")
    conn.commit()
    return RedirectResponse(url="/erp_fa", status_code=303)


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


@router.get("/slip_list", response_class=HTMLResponse)
async def slip_list(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        """SELECT e.*, u.name as author_name
           FROM erp_docs e
           LEFT JOIN users u ON e.user_id = u.id
           WHERE e.doc_type='expense' AND e.slip_type != ''
           ORDER BY e.id DESC"""
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/slip_list.html", context={
        "request": request, "page_title": "전표 조회",
        "user_name": u["user_name"],
        "docs": docs,
    })


@router.get("/edit_slip/{doc_id}", response_class=HTMLResponse)
async def edit_slip(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
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
            "user_name": u["user_name"],
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
    u: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = u["user_id"]
    uname = u["user_name"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
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

    result = await save_upload(attachment)
    if isinstance(result, JSONResponse):
        return result
    saved_name = result if result else (doc["attachment"] or "")

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
    insert_approval_lines(conn, doc_id, uid, reviewer_id, approver_id, is_draft, now, uname, "수정")
    conn.commit()
    return RedirectResponse(url="/erp_fa", status_code=303)


@router.post("/api/slip/{doc_id}/delete")
async def delete_slip(request: Request, doc_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
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
    return templates.TemplateResponse(request=request, name="erp/trade_statement.html", context={
        "request": request, "doc": dict(doc), "slip_lines": slip_lines_data,
        "company": {"name": "(주)원플러스", "biz_no": "123-86-00001", "representative": "대표이사",
                     "address": "서울특별시 강남구 테헤란로 123", "biz_type": "서비스업", "biz_item": "소프트웨어 개발"},
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
        "company": {"name": "(주)원플러스", "biz_no": "123-86-00001", "representative": "대표이사",
                     "address": "서울특별시 강남구 테헤란로 123"},
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
    return templates.TemplateResponse(request=request, name="erp/tax_invoice.html", context={
        "request": request, "doc": dict(doc), "slip_lines": slip_lines_data,
        "company": {"name": "(주)원플러스", "biz_no": "123-86-00001", "representative": "대표이사",
                     "address": "서울특별시 강남구 테헤란로 123", "biz_type": "서비스업", "biz_item": "소프트웨어 개발"},
    })
