import sqlite3
from urllib.parse import quote
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.task_link import stamp_task, erp_scope, task_locked
from core.deps import get_db, require_login, templates
from core.erp_log import log_activity
from core.tz import now_kst, today_kst
from core import audit, books, invoices, partner, returns, stock

router = APIRouter()

PER_PAGE = 20

PO_STATUS = {
    "draft": "임시저장",
    "pending_approval": "결재대기",
    "confirmed": "확정",
    "partial": "부분입고",
    "completed": "입고완료",
    "cancelled": "취소",
}

PO_STATUS_CLASS = {
    "draft": "status-badge status-wait",
    "pending_approval": "status-badge status-progress",
    "confirmed": "status-badge status-progress",
    "partial": "status-badge status-progress",
    "completed": "status-badge status-done",
    "cancelled": "status-badge status-reject",
}

GR_STATUS = {
    "draft": "임시저장",
    "confirmed": "확정",
}


def _next_po_number(conn, seq_hint=None):
    year = today_kst().year
    if seq_hint is None:
        row = conn.execute(
            "SELECT po_number FROM purchase_orders WHERE po_number LIKE ? ORDER BY id DESC LIMIT 1",
            (f"PO-{year}-%",),
        ).fetchone()
        seq_hint = int(row["po_number"].split("-")[-1]) + 1 if row else 1
    return f"PO-{year}-{seq_hint:04d}", seq_hint


def _next_gr_number(conn, seq_hint=None):
    year = today_kst().year
    if seq_hint is None:
        row = conn.execute(
            "SELECT gr_number FROM goods_receipts WHERE gr_number LIKE ? ORDER BY id DESC LIMIT 1",
            (f"GR-{year}-%",),
        ).fetchone()
        seq_hint = int(row["gr_number"].split("-")[-1]) + 1 if row else 1
    return f"GR-{year}-{seq_hint:04d}", seq_hint


@router.get("/api/items/search")
async def api_items_search(request: Request, q: str = "",
                           u: dict = Depends(books.require_book), conn=Depends(get_db)):
    sql = "SELECT id, item_code, item_name, unit, unit_price FROM items WHERE company_id=? AND is_active=1"
    params = [u["book"]]
    if q:
        sql += " AND (item_code LIKE ? OR item_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY item_code LIMIT 20"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    return rows


@router.get("/purchase-orders", response_class=HTMLResponse)
async def po_list(request: Request, status: str = "", partner: str = "", page: int = 1,
                  u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "po")
    base_where = f"WHERE {scope_sql}"
    params = [*scope_args]
    if status:
        base_where += " AND po.status=?"
        params.append(status)
    if partner:
        base_where += " AND (p.name LIKE ? OR p.code LIKE ?)"
        params += [f"%{partner}%", f"%{partner}%"]

    total = conn.execute(
        f"SELECT COUNT(*) FROM purchase_orders po LEFT JOIN partners p ON po.partner_id=p.id {base_where}",
        params,
    ).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    sql = f"""
        SELECT po.*, p.name as partner_name
        FROM purchase_orders po
        LEFT JOIN partners p ON po.partner_id=p.id
        {base_where}
        ORDER BY po.id DESC
        LIMIT {PER_PAGE} OFFSET {(page-1)*PER_PAGE}
    """
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["status_label"] = PO_STATUS.get(r["status"], r["status"])
        r["status_class"] = PO_STATUS_CLASS.get(r["status"], "")
    return templates.TemplateResponse(request=request, name="erp/po_list.html", context={
        "request": request, "page_title": "발주 목록",
        "user_name": u["name"],
        "orders": rows, "status": status, "partner": partner,
        "po_status": PO_STATUS,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/purchase-orders?status={status}&partner={partner}",
    })


@router.get("/purchase-orders/new", response_class=HTMLResponse)
async def po_form_new(request: Request, partner_id: int = 0,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    partners = [dict(r) for r in conn.execute(
        """SELECT id, code, name FROM partners WHERE company_id=? AND is_active=1
           AND partner_type IN ('supplier','both') ORDER BY code""", (books.book_of(conn, u),)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/po_form.html", context={
        "request": request, "page_title": "발주서 작성",
        "user_name": u["name"],
        "po": None, "partners": partners, "pre_partner": partner_id,
        "today": today_kst().isoformat(),
    })


@router.get("/purchase-orders/unreceived", response_class=HTMLResponse)
async def po_unreceived(request: Request, q: str = "", overdue: int = 0,
                        u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "po")
    where = f"WHERE {scope_sql} AND po.status IN ('confirmed','partial') AND pl.quantity > pl.received_qty - pl.returned_qty"
    params = [*scope_args]
    if q:
        where += " AND (p.name LIKE ? OR i.item_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if overdue:
        where += " AND po.delivery_date < ?"
        params.append(today_kst().isoformat())
    rows = [dict(r) for r in conn.execute(
        f"""SELECT po.id AS doc_id, po.po_number AS doc_no, po.po_date AS doc_date, po.delivery_date, p.name AS partner,
                   i.item_code, i.item_name, pl.quantity, pl.received_qty AS done, pl.returned_qty, pl.unit_price
            FROM po_lines pl JOIN purchase_orders po ON po.id=pl.po_id JOIN items i ON i.id=pl.item_id
            LEFT JOIN partners p ON p.id=po.partner_id
            {where} ORDER BY po.delivery_date, po.id, pl.line_no""",
        params,
    ).fetchall()]
    for r in rows:
        r["remain"] = r["quantity"] - r["done"] + r["returned_qty"]
        r["amt"] = r["remain"] * r["unit_price"]
    return templates.TemplateResponse(request=request, name="erp/backlog.html", context={
        "request": request, "page_title": "미입고 현황", "user_name": u["name"],
        "rows": rows, "q": q, "overdue": overdue, "today": today_kst().isoformat(),
        "total_qty": sum(r["remain"] for r in rows), "total_amt": sum(r["amt"] for r in rows),
        "base": "/purchase-orders", "label": "입고",
    })


@router.get("/purchase-orders/{po_id}/edit", response_class=HTMLResponse)
async def po_form_edit(request: Request, po_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "po")
    po = conn.execute(
        f"SELECT po.* FROM purchase_orders po WHERE po.id=? AND {scope_sql}",
        (po_id, *scope_args),
    ).fetchone()
    if not po or po["status"] != "draft":
        return RedirectResponse("/purchase-orders", status_code=303)
    po = dict(po)
    po["lines"] = [dict(r) for r in conn.execute(
        """SELECT pl.*, i.item_code, i.item_name, i.unit
           FROM po_lines pl JOIN items i ON pl.item_id=i.id
           WHERE pl.po_id=? ORDER BY pl.line_no""", (po_id,)
    ).fetchall()]
    partners = [dict(r) for r in conn.execute(
        """SELECT id, code, name FROM partners WHERE company_id=? AND is_active=1
           AND partner_type IN ('supplier','both') ORDER BY code""", (books.book_of(conn, u),)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/po_form.html", context={
        "request": request, "page_title": "발주서 수정",
        "user_name": u["name"],
        "po": po, "partners": partners,
        "today": today_kst().isoformat(),
    })


@router.post("/purchase-orders/save")
async def po_save(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    po_id = int(form.get("po_id", 0) or 0)
    partner_id = int(form.get("partner_id", 0) or 0)
    po_date = form.get("po_date", today_kst().isoformat())
    delivery_date = form.get("delivery_date", "")
    notes = form.get("notes", "")

    book = books.book_of(conn, u)
    if not partner_id or not conn.execute(
        """SELECT 1 FROM partners WHERE id=? AND company_id=?
           AND partner_type IN ('supplier','both')""", (partner_id, book)
    ).fetchone():
        return JSONResponse({"error": "거래처를 찾을 수 없습니다."}, status_code=400)

    contact_id = partner.own_contact(conn, book, partner_id, form.get("contact_id"))

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    total = 0
    for ln in line_nums:
        item_id = int(form.get(f"item_id_{ln}", 0) or 0)
        qty = int(str(form.get(f"qty_{ln}", 0) or 0).replace(",", ""))
        price = int(str(form.get(f"price_{ln}", 0) or 0).replace(",", ""))
        if item_id and qty > 0 and conn.execute(
            "SELECT 1 FROM items WHERE id=? AND company_id=?", (item_id, book)
        ).fetchone():
            amt = qty * price
            lines.append((item_id, qty, price, amt))
            total += amt

    if not lines:
        return RedirectResponse("/purchase-orders/new", status_code=303)

    tax = int(total * 0.1)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    is_new = not bool(po_id)

    try:
        over = partner.guard(conn, book, partner_id, total + tax, po_date, "발주", ar=False)
    except ValueError:
        return JSONResponse({"error": "발주일을 확인해 주세요."}, status_code=400)
    if over and (over["block"] or not form.get("credit_ok")):
        return partner.credit_reply(over)

    if po_id:
        scope_sql, scope_args = erp_scope(conn, u, "po")
        existing = conn.execute(
            f"SELECT task_id FROM purchase_orders po WHERE po.id=? AND {scope_sql}", (po_id, *scope_args)
        ).fetchone()
        if not existing:
            return RedirectResponse("/purchase-orders", status_code=303)
        if task_locked(conn, existing["task_id"]):
            return RedirectResponse(f"/purchase-orders/{po_id}?error=locked", status_code=303)
        conn.execute(
            """UPDATE purchase_orders SET partner_id=?, po_date=?, delivery_date=?,
               total_amount=?, tax_amount=?, notes=?, contact_id=?, updated_at=? WHERE id=? AND status='draft'""",
            (partner_id or None, po_date, delivery_date, total, tax, notes, contact_id, now, po_id),
        )
        conn.execute("DELETE FROM po_lines WHERE po_id=?", (po_id,))
    else:
        po_number, seq = _next_po_number(conn)
        task_id = stamp_task(conn, request, u["id"], "purchase")
        while True:
            try:
                cur = conn.execute(
                    """INSERT INTO purchase_orders (po_number, partner_id, po_date, delivery_date,
                       total_amount, tax_amount, notes, contact_id, created_by, task_id, company_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (po_number, partner_id or None, po_date, delivery_date, total, tax, notes, contact_id,
                     u["id"], task_id, book),
                )
                break
            except sqlite3.IntegrityError:
                seq += 1
                po_number, _ = _next_po_number(conn, seq)
        po_id = cur.lastrowid

    for i, (item_id, qty, price, amt) in enumerate(lines, 1):
        conn.execute(
            "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,?,?,?,?,?)",
            (po_id, i, item_id, qty, price, amt),
        )

    if is_new:
        prow = conn.execute("SELECT name FROM partners WHERE id=?", (partner_id,)).fetchone()
        pname = prow["name"] if prow else ""
        log_activity(conn, u["id"], "create", "purchase", po_id, po_number, f"발주서 작성 {po_number} ({pname}, {total:,}원)")
    else:
        prow = conn.execute("SELECT po_number, partner_id FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
        po_number = prow["po_number"] if prow else ""
        p2 = conn.execute("SELECT name FROM partners WHERE id=?", (partner_id,)).fetchone()
        pname = p2["name"] if p2 else ""
        log_activity(conn, u["id"], "update", "purchase", po_id, po_number, f"발주서 수정 {po_number} ({pname}, {total:,}원)")

    conn.commit()
    return RedirectResponse(f"/purchase-orders/{po_id}", status_code=303)


@router.get("/purchase-orders/{po_id}", response_class=HTMLResponse)
async def po_detail(request: Request, po_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "po")
    po = conn.execute(
        f"""SELECT po.*, p.name as partner_name, p.code as partner_code,
                  p.biz_no as partner_biz_no, p.phone as partner_phone,
                  c.name as partner_contact, COALESCE(NULLIF(c.mobile, ''), c.phone) as partner_contact_phone,
                  c.email as partner_contact_email,
                  u.name as creator_name
           FROM purchase_orders po
           LEFT JOIN partners p ON po.partner_id=p.id
           LEFT JOIN partner_contacts c ON c.id=COALESCE(po.contact_id,
                                                (SELECT id FROM partner_contacts
                                                 WHERE partner_id=p.id AND is_primary=1 LIMIT 1))
           LEFT JOIN users u ON po.created_by=u.id
           WHERE po.id=? AND {scope_sql}""", (po_id, *scope_args)
    ).fetchone()
    if not po:
        return RedirectResponse("/purchase-orders", status_code=303)
    po = dict(po)
    po["status_label"] = PO_STATUS.get(po["status"], po["status"])
    po["status_class"] = PO_STATUS_CLASS.get(po["status"], "")

    lines = [dict(r) for r in conn.execute(
        """SELECT pl.*, i.item_code, i.item_name, i.unit
           FROM po_lines pl JOIN items i ON pl.item_id=i.id
           WHERE pl.po_id=? ORDER BY pl.line_no""", (po_id,)
    ).fetchall()]

    grs = [dict(r) for r in conn.execute(
        """SELECT gr.*, w.name as warehouse_name, ti.id AS inv_id, ti.total AS inv_total, d.id AS doc_id, d.slip_no
           FROM goods_receipts gr
           LEFT JOIN warehouses w ON gr.warehouse_id=w.id
           LEFT JOIN tax_invoices ti ON ti.source_type='gr' AND ti.source_id=gr.id
           LEFT JOIN erp_docs d ON d.source_type='gr' AND d.source_id=gr.id
           WHERE gr.po_id=? ORDER BY gr.id DESC""", (po_id,)
    ).fetchall()]
    for g in grs:
        g["status_label"] = GR_STATUS.get(g["status"], g["status"])

    approval = conn.execute(
        "SELECT a.*, u.name as approver_name FROM approvals a LEFT JOIN users u ON a.approver_id=u.id WHERE a.doc_type='po' AND a.doc_id=? ORDER BY a.id DESC LIMIT 1",
        (po_id,),
    ).fetchone()
    approval = dict(approval) if approval else None
    can_approve = bool(
        approval and approval["status"] == "pending"
        and (approval["approver_id"] == u["id"] or partner.can_edit(u))
    )

    return templates.TemplateResponse(request=request, name="erp/po_detail.html", context={
        "request": request, "page_title": f"발주서 {po['po_number']}",
        "user_name": u["name"], "user_role": u["role"],
        "po": po, "lines": lines, "grs": grs,
        "approval": approval,
        "approvers": [a for a in books.book_users(conn, po["company_id"]) if a["id"] != u["id"]],
        "can_approve": can_approve,
    })


@router.post("/purchase-orders/{po_id}/confirm")
async def po_confirm(request: Request, po_id: int, approver_id: int = Form(0),
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "po")
    po = conn.execute(f"SELECT status, company_id FROM purchase_orders po WHERE po.id=? AND {scope_sql}", (po_id, *scope_args)).fetchone()
    if not po or po["status"] != "draft":
        return JSONResponse({"error": "확정할 수 없는 상태입니다."}, status_code=400)
    candidates = [c["id"] for c in books.book_users(conn, po["company_id"]) if c["id"] != u["id"]]
    if approver_id not in candidates:
        return JSONResponse({"error": "결재자를 선택해 주세요."}, status_code=400)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "UPDATE purchase_orders SET status='pending_approval', updated_at=? WHERE id=?",
        (now, po_id),
    )
    conn.execute(
        "INSERT INTO approvals (doc_type, doc_id, step, approver_id) VALUES ('po', ?, 1, ?)",
        (po_id, approver_id),
    )

    po_info = conn.execute("SELECT po_number FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
    log_activity(conn, u["id"], "submit", "purchase", po_id, po_info["po_number"], f"발주 결재요청 {po_info['po_number']}")

    conn.commit()
    return RedirectResponse(f"/purchase-orders/{po_id}", status_code=303)


@router.post("/purchase-orders/{po_id}/approve")
async def po_approve(request: Request, po_id: int,
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "po")
    po = conn.execute(f"SELECT status, company_id FROM purchase_orders po WHERE po.id=? AND {scope_sql}", (po_id, *scope_args)).fetchone()
    if not po or po["status"] != "pending_approval":
        return JSONResponse({"error": "승인할 수 없는 상태입니다."}, status_code=400)
    appr = conn.execute(
        "SELECT * FROM approvals WHERE doc_type='po' AND doc_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
        (po_id,),
    ).fetchone()
    if not appr or not (appr["approver_id"] == u["id"] or partner.can_edit(u)):
        raise HTTPException(status_code=403)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE purchase_orders SET status='confirmed', updated_at=? WHERE id=?",
        (now, po_id),
    )
    # 지정 결재자는 유지. 대행 처리자는 감사 로그에만 기록
    conn.execute(
        "UPDATE approvals SET status='approved', acted_at=? WHERE id=?",
        (now, appr["id"]),
    )
    po_info = conn.execute("SELECT po_number FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
    log_activity(conn, u["id"], "approve", "purchase", po_id, po_info["po_number"], f"발주 승인 {po_info['po_number']}")
    audit.log(conn, u["id"], "po_approve", "po", po_id, po_info["po_number"], company_id=po["company_id"])
    conn.commit()
    return RedirectResponse(f"/purchase-orders/{po_id}", status_code=303)


@router.post("/purchase-orders/{po_id}/reject")
async def po_reject(request: Request, po_id: int,
                    comment: str = Form(""),
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "po")
    po = conn.execute(f"SELECT status, company_id FROM purchase_orders po WHERE po.id=? AND {scope_sql}", (po_id, *scope_args)).fetchone()
    if not po or po["status"] != "pending_approval":
        return JSONResponse({"error": "반려할 수 없는 상태입니다."}, status_code=400)
    appr = conn.execute(
        "SELECT * FROM approvals WHERE doc_type='po' AND doc_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
        (po_id,),
    ).fetchone()
    if not appr or not (appr["approver_id"] == u["id"] or partner.can_edit(u)):
        raise HTTPException(status_code=403)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE purchase_orders SET status='draft', updated_at=? WHERE id=?",
        (now, po_id),
    )
    conn.execute(
        "UPDATE approvals SET status='rejected', comment=?, acted_at=? WHERE id=?",
        (comment, now, appr["id"]),
    )
    po_info = conn.execute("SELECT po_number FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
    log_activity(conn, u["id"], "reject", "purchase", po_id, po_info["po_number"], f"발주 반려 {po_info['po_number']}")
    audit.log(conn, u["id"], "po_reject", "po", po_id, po_info["po_number"], company_id=po["company_id"])
    conn.commit()
    return RedirectResponse(f"/purchase-orders/{po_id}", status_code=303)


@router.post("/purchase-orders/{po_id}/cancel")
async def po_cancel(request: Request, po_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "po")
    po = conn.execute(
        f"SELECT status, task_id FROM purchase_orders po WHERE po.id=? AND {scope_sql}", (po_id, *scope_args)
    ).fetchone()
    if not po or po["status"] not in ("draft", "confirmed"):
        return JSONResponse({"error": "취소할 수 없는 상태입니다."}, status_code=400)
    if task_locked(conn, po["task_id"]):
        return JSONResponse({"error": "승인된 태스크의 발주는 취소할 수 없습니다"}, status_code=403)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE purchase_orders SET status='cancelled', updated_at=? WHERE id=?",
        (now, po_id),
    )
    po_info = conn.execute("SELECT po_number FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
    log_activity(conn, u["id"], "cancel", "purchase", po_id, po_info["po_number"], f"발주 취소 {po_info['po_number']}")
    conn.commit()
    return RedirectResponse(f"/purchase-orders/{po_id}", status_code=303)


@router.get("/goods-receipts/new", response_class=HTMLResponse)
async def gr_form_new(request: Request, po_id: int = 0,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    po = None
    po_lines = []
    if po_id:
        scope_sql, scope_args = erp_scope(conn, u, "po")
        po = conn.execute(
            f"""SELECT po.*, p.name as partner_name
               FROM purchase_orders po
               LEFT JOIN partners p ON po.partner_id=p.id
               WHERE po.id=? AND po.status IN ('confirmed','partial') AND {scope_sql}""", (po_id, *scope_args)
        ).fetchone()
        if po:
            po = dict(po)
            po_lines = [dict(r) for r in conn.execute(
                """SELECT pl.*, i.item_code, i.item_name, i.unit,
                          (pl.quantity - pl.received_qty + pl.returned_qty) as remaining_qty
                   FROM po_lines pl JOIN items i ON pl.item_id=i.id
                   WHERE pl.po_id=? AND pl.quantity > pl.received_qty - pl.returned_qty
                   ORDER BY pl.line_no""", (po_id,)
            ).fetchall()]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code",
        (books.book_of(conn, u),)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/gr_form.html", context={
        "request": request, "page_title": "입고 등록",
        "user_name": u["name"],
        "po": po, "po_lines": po_lines, "warehouses": warehouses,
        "today": today_kst().isoformat(),
    })


@router.post("/goods-receipts/save")
async def gr_save(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    po_id = int(form.get("po_id", 0) or 0)
    warehouse_id = int(form.get("warehouse_id", 0) or 0)
    receipt_date = form.get("receipt_date", today_kst().isoformat())
    notes = form.get("notes", "")

    po_company = books.book_of(conn, u)
    if po_id:
        scope_sql, scope_args = erp_scope(conn, u, "po")
        po_row = conn.execute(
            f"SELECT company_id FROM purchase_orders po WHERE po.id=? AND {scope_sql}", (po_id, *scope_args)
        ).fetchone()
        if not po_row:
            return RedirectResponse(f"/goods-receipts/new?po_id={po_id}", status_code=303)
        po_company = po_row["company_id"]

    if not warehouse_id or not conn.execute(
        "SELECT 1 FROM warehouses WHERE id=? AND company_id=?", (warehouse_id, po_company)
    ).fetchone():
        return RedirectResponse(f"/goods-receipts/new?po_id={po_id}", status_code=303)

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    for ln in line_nums:
        po_line_id = int(form.get(f"po_line_id_{ln}", 0) or 0)
        item_id = int(form.get(f"item_id_{ln}", 0) or 0)
        recv_qty = int(str(form.get(f"recv_qty_{ln}", 0) or 0).replace(",", ""))
        defect_qty = int(str(form.get(f"defect_qty_{ln}", 0) or 0).replace(",", ""))
        if po_line_id:
            # 발주 라인은 해당 발주 소속만 허용, 품목도 발주 라인 기준
            pol = conn.execute(
                "SELECT item_id FROM po_lines WHERE id=? AND po_id=?", (po_line_id, po_id)
            ).fetchone()
            if not pol:
                continue
            item_id = pol["item_id"]
        if item_id and recv_qty > 0 and 0 <= defect_qty <= recv_qty and conn.execute(
            "SELECT 1 FROM items WHERE id=? AND company_id=?", (item_id, po_company)
        ).fetchone():
            lines.append((po_line_id, item_id, recv_qty, defect_qty))

    if not lines:
        return RedirectResponse(f"/goods-receipts/new?po_id={po_id}", status_code=303)

    if po_id:
        for po_line_id, item_id, recv_qty, defect_qty in lines:
            if not po_line_id:
                continue
            pol = conn.execute(
                "SELECT quantity, COALESCE(received_qty,0) AS rcvd, COALESCE(returned_qty,0) AS ret FROM po_lines WHERE id=?",
                (po_line_id,)
            ).fetchone()
            net = pol["rcvd"] - pol["ret"] + recv_qty if pol else 0
            if pol and net > int(pol["quantity"] * 1.1):
                item = conn.execute("SELECT item_name FROM items WHERE id=?", (item_id,)).fetchone()
                msg = f"과다입고: {item['item_name']} (발주 {pol['quantity']}, 누적 {net})"
                return RedirectResponse(
                    f"/goods-receipts/new?po_id={po_id}&error={quote(msg)}",
                    status_code=303,
                )

    uid = u["id"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    gr_number, gr_seq = _next_gr_number(conn)
    task_id = stamp_task(conn, request, uid, "purchase")

    while True:
        try:
            cur = conn.execute(
                """INSERT INTO goods_receipts (gr_number, po_id, warehouse_id, receipt_date, status, notes, created_by, task_id, company_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (gr_number, po_id or None, warehouse_id, receipt_date, "confirmed", notes, uid, task_id, po_company),
            )
            break
        except sqlite3.IntegrityError:
            gr_seq += 1
            gr_number, _ = _next_gr_number(conn, gr_seq)
    gr_id = cur.lastrowid

    total_amount = 0
    inv_items = []
    for i, (po_line_id, item_id, recv_qty, defect_qty) in enumerate(lines, 1):
        conn.execute(
            "INSERT INTO gr_lines (gr_id, po_line_id, item_id, received_qty, defective_qty) VALUES (?,?,?,?,?)",
            (gr_id, po_line_id or None, item_id, recv_qty, defect_qty),
        )

        good_qty = recv_qty - defect_qty
        pl = None
        if po_line_id:
            conn.execute(
                "UPDATE po_lines SET received_qty = received_qty + ? WHERE id=?",
                (recv_qty, po_line_id),
            )
            pl = conn.execute(
                "SELECT pl.unit_price, i.item_name FROM po_lines pl JOIN items i ON pl.item_id=i.id WHERE pl.id=?",
                (po_line_id,),
            ).fetchone()
        if good_qty:
            stock.move_in(conn, item_id, warehouse_id, good_qty, receipt_date, "gr", gr_id, uid,
                          pl["unit_price"] if pl else None)
            if pl:
                total_amount += good_qty * pl["unit_price"]
                inv_items.append({"name": pl["item_name"], "qty": good_qty, "unit_price": pl["unit_price"],
                                  "supply_amt": good_qty * pl["unit_price"]})

    if po_id:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM po_lines WHERE po_id=? AND quantity > received_qty - returned_qty",
            (po_id,),
        ).fetchone()[0]
        if remaining == 0:
            conn.execute("UPDATE purchase_orders SET status='completed', updated_at=? WHERE id=?", (now, po_id))
        else:
            po_row = conn.execute("SELECT status FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
            if po_row and po_row["status"] == "confirmed":
                conn.execute("UPDATE purchase_orders SET status='partial', updated_at=? WHERE id=?", (now, po_id))

    if total_amount > 0:
        partner_id = None
        if po_id:
            po = conn.execute("SELECT partner_id FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
            if po:
                partner_id = po["partner_id"]
        book = books.book_of(conn, u)
        try:
            _create_gr_slip(conn, book, gr_id, gr_number, total_amount, uid, receipt_date, partner_id, inv_items)
        except ValueError as e:
            conn.rollback()
            return JSONResponse({"error": str(e)}, status_code=400)

    po_number_str = ""
    if po_id:
        po_row2 = conn.execute("SELECT po_number FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
        if po_row2:
            po_number_str = po_row2["po_number"]
    log_activity(conn, u["id"], "create", "purchase", gr_id, gr_number, f"입고 등록 {gr_number} (PO: {po_number_str})")
    audit.log(conn, u["id"], "gr_confirm", "gr", gr_id, gr_number, company_id=po_company)

    conn.commit()
    return RedirectResponse(f"/goods-receipts/{gr_id}", status_code=303)


def _create_gr_slip(conn, book, gr_id, gr_number, amount, uid, receipt_date, partner_id, items=()):
    tax_type, evidence, vat = invoices.terms(conn, partner_id, amount)
    inv = {"kind": "매입", "tax_type": tax_type, "evidence": evidence, "issue_date": receipt_date,
           "partner_id": partner_id, "supply_amt": amount, "vat": vat, "source_type": "gr", "source_id": gr_id,
           "deduct": 1}
    lines = invoices.inv_lines(inv, "120", "251", f"입고 {gr_number}")
    doc_id = books.post(conn, book, uid, receipt_date, lines, f"입고 전표 ({gr_number})", "gr", gr_id,
                        content=f"입고번호 {gr_number} 자동 생성 전표")
    invoices.add(conn, book, uid, {**inv, "doc_id": doc_id}, items)
    return doc_id


@router.get("/goods-receipts/{gr_id}", response_class=HTMLResponse)
async def gr_detail(request: Request, gr_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "gr")
    gr = conn.execute(
        f"""SELECT gr.*, w.name as warehouse_name, u.name as creator_name,
                  po.po_number, p.name as partner_name
           FROM goods_receipts gr
           LEFT JOIN warehouses w ON gr.warehouse_id=w.id
           LEFT JOIN users u ON gr.created_by=u.id
           LEFT JOIN purchase_orders po ON gr.po_id=po.id
           LEFT JOIN partners p ON po.partner_id=p.id
           WHERE gr.id=? AND {scope_sql}""", (gr_id, *scope_args)
    ).fetchone()
    if not gr:
        return RedirectResponse("/purchase-orders", status_code=303)
    gr = dict(gr)
    gr["status_label"] = GR_STATUS.get(gr["status"], gr["status"])

    lines = [dict(r) for r in conn.execute(
        """SELECT gl.*, i.item_code, i.item_name, i.unit
           FROM gr_lines gl JOIN items i ON gl.item_id=i.id
           WHERE gl.gr_id=? ORDER BY gl.id""", (gr_id,)
    ).fetchall()]

    can_return = False
    return_hist = []
    if gr["kind"] == "반품":
        orig = conn.execute(
            """SELECT og.id, og.gr_number FROM gr_lines l JOIN gr_lines ol ON ol.id=l.orig_line_id
               JOIN goods_receipts og ON og.id=ol.gr_id WHERE l.gr_id=? LIMIT 1""", (gr_id,)
        ).fetchone()
        gr["orig_gr_id"] = orig["id"] if orig else None
        gr["orig_gr_number"] = orig["gr_number"] if orig else None
    else:
        if gr["status"] == "confirmed":
            can_return = sum(returns.limits(conn, gr["company_id"], "gr", gr_id).values()) > 0
        return_hist = [dict(r) for r in conn.execute(
            """SELECT rg.id, rg.gr_number, rg.receipt_date, rg.canceled_at, SUM(rl.received_qty) AS qty
               FROM gr_lines rl JOIN goods_receipts rg ON rg.id=rl.gr_id
               WHERE rl.orig_line_id IN (SELECT id FROM gr_lines WHERE gr_id=?)
               GROUP BY rg.id ORDER BY rg.id DESC""", (gr_id,)
        ).fetchall()]

    return templates.TemplateResponse(request=request, name="erp/gr_detail.html", context={
        "request": request, "page_title": f"입고 {gr['gr_number']}",
        "user_name": u["name"], "can_edit": partner.can_edit(u),
        "gr": gr, "lines": lines, "can_return": can_return, "return_hist": return_hist,
    })


@router.get("/goods-receipts/{gr_id}/return", response_class=HTMLResponse)
async def gr_return_form(request: Request, gr_id: int,
                         u: dict = Depends(require_login), conn=Depends(get_db)):
    book = books.book_of(conn, u)
    try:
        cap = returns.limits(conn, book, "gr", gr_id)
    except LookupError:
        raise HTTPException(status_code=404)
    gr = conn.execute("SELECT gr_number FROM goods_receipts WHERE id=?", (gr_id,)).fetchone()
    lines = [dict(r) for r in conn.execute(
        """SELECT l.id, l.received_qty AS orig_qty, i.item_code, i.item_name, i.unit
           FROM gr_lines l JOIN items i ON i.id=l.item_id
           WHERE l.gr_id=? ORDER BY l.id""", (gr_id,)
    ).fetchall()]
    for l in lines:
        l["cap"] = cap.get(l["id"], 0)
    return templates.TemplateResponse(request=request, name="erp/return_form.html", context={
        "request": request, "page_title": f"입고 반품 ({gr['gr_number']})",
        "user_name": u["name"], "typ": "gr", "doc_number": gr["gr_number"],
        "action": f"/goods-receipts/{gr_id}/return", "back": f"/goods-receipts/{gr_id}",
        "lines": lines, "today": today_kst().isoformat(),
    })


@router.post("/goods-receipts/{gr_id}/return")
async def gr_return_save(request: Request, gr_id: int,
                         u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    book = books.book_of(conn, u)
    ret_date = form.get("ret_date", today_kst().isoformat())
    notes = form.get("notes", "")
    try:
        cap = returns.limits(conn, book, "gr", gr_id)
    except LookupError:
        raise HTTPException(status_code=404)
    qtys = {}
    for lid in cap:
        qty = int(str(form.get(f"qty_{lid}", 0) or 0).replace(",", "") or 0)
        if qty:
            qtys[lid] = qty

    number, seq = _next_gr_number(conn)
    while True:
        try:
            ret_id = returns.create(conn, book, u["id"], "gr", gr_id, ret_date, qtys, notes, number)
            break
        except sqlite3.IntegrityError:
            seq += 1
            number, _ = _next_gr_number(conn, seq)
        except LookupError:
            raise HTTPException(status_code=404)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    log_activity(conn, u["id"], "create", "purchase", ret_id, number, f"입고 반품 등록 {number} (입고 {gr_id})")
    conn.commit()
    return RedirectResponse(f"/goods-receipts/{ret_id}", status_code=303)


@router.delete("/goods-receipts/{gr_id}")
async def gr_return_cancel(gr_id: int, u: dict = Depends(partner.require_editor), conn=Depends(get_db)):
    gr = conn.execute("SELECT kind, gr_number FROM goods_receipts WHERE id=? AND company_id=?",
                      (gr_id, u["book"])).fetchone()
    if not gr or gr["kind"] != "반품":
        raise HTTPException(status_code=404)
    try:
        returns.cancel(conn, u["book"], u["id"], "gr", gr_id)
    except LookupError:
        raise HTTPException(status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    log_activity(conn, u["id"], "cancel", "purchase", gr_id, gr["gr_number"], f"입고 반품 취소 {gr['gr_number']}")
    conn.commit()
    return JSONResponse({"ok": True})


@router.get("/purchase-orders/{po_id}/statement", response_class=HTMLResponse)
async def po_statement(request: Request, po_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "po")
    po = conn.execute(
        f"""SELECT po.*, p.name as partner_name, p.biz_no as partner_biz_no,
                  p.representative as partner_rep, p.address as partner_addr,
                  p.biz_type as partner_biz_type, p.biz_item as partner_biz_item,
                  u.name as creator_name, ct.name as contact_name,
                  COALESCE(NULLIF(ct.mobile, ''), ct.phone) as contact_phone
           FROM purchase_orders po
           LEFT JOIN partners p ON po.partner_id=p.id
           LEFT JOIN users u ON po.created_by=u.id
           LEFT JOIN partner_contacts ct ON ct.id=COALESCE(po.contact_id,
                                                (SELECT id FROM partner_contacts
                                                 WHERE partner_id=p.id AND is_primary=1 LIMIT 1))
           WHERE po.id=? AND {scope_sql}""", (po_id, *scope_args)
    ).fetchone()
    if not po:
        return RedirectResponse("/purchase-orders", status_code=303)

    lines = [dict(r) for r in conn.execute(
        """SELECT pl.*, i.item_code, i.item_name, i.unit
           FROM po_lines pl JOIN items i ON pl.item_id=i.id
           WHERE pl.po_id=? ORDER BY pl.line_no""", (po_id,)
    ).fetchall()]

    book = books.book_of(conn, u) or books.INTERNAL
    return templates.TemplateResponse(request=request, name="erp/trade_statement.html", context={
        "request": request, "doc_type": "purchase",
        "doc_number": po["po_number"], "doc_date": po["po_date"],
        "supplier": books.company_info(conn, book),
        "buyer": {
            "name": po["partner_name"] or "", "biz_no": po["partner_biz_no"] or "",
            "representative": po["partner_rep"] or "", "address": po["partner_addr"] or "",
            "biz_type": po["partner_biz_type"] or "", "biz_item": po["partner_biz_item"] or "",
        },
        "contact_name": po["contact_name"] or "", "contact_phone": po["contact_phone"] or "",
        "lines": lines,
        "total_amount": po["total_amount"], "tax_amount": po["tax_amount"],
    })
