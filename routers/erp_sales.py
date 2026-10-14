import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.task_link import stamp_task, erp_scope, task_locked
from core.deps import get_db, require_login, templates
from core.erp_log import log_activity
from core.tz import today_kst
from core import audit, books, invoices, partner, returns, stock

router = APIRouter()

PER_PAGE = 20

QT_STATUS = {
    "draft": "임시저장",
    "sent": "발송",
    "accepted": "수락",
    "rejected": "거절",
    "expired": "만료",
}

QT_STATUS_CLASS = {
    "draft": "status-badge status-wait",
    "sent": "status-badge status-progress",
    "accepted": "status-badge status-done",
    "rejected": "status-badge status-reject",
    "expired": "status-badge status-reject",
}

SO_STATUS = {
    "confirmed": "확정",
    "picking": "출고준비",
    "shipped": "출고완료",
    "invoiced": "청구완료",
    "cancelled": "취소",
}

SO_STATUS_CLASS = {
    "confirmed": "status-badge status-progress",
    "picking": "status-badge status-progress",
    "shipped": "status-badge status-done",
    "invoiced": "status-badge status-done",
    "cancelled": "status-badge status-reject",
}

SHIP_STATUS = {
    "draft": "임시저장",
    "confirmed": "확정",
}


def _next_number(conn, prefix, table, column, seq_hint=None):
    year = today_kst().year
    if seq_hint is None:
        pat = f"{prefix}-{year}-%"
        row = conn.execute(
            f"SELECT {column} FROM {table} WHERE {column} LIKE ? ORDER BY id DESC LIMIT 1",
            (pat,),
        ).fetchone()
        seq_hint = int(row[column].split("-")[-1]) + 1 if row else 1
    return f"{prefix}-{year}-{seq_hint:04d}", seq_hint


@router.get("/quotations", response_class=HTMLResponse)
async def quote_list(request: Request, status: str = "", customer: str = "", page: int = 1,
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    conn.execute(
        "UPDATE quotations SET status='expired' WHERE status='sent' AND valid_until < ?",
        (today_kst().isoformat(),),
    )
    conn.commit()

    scope_sql, scope_args = erp_scope(conn, u, "q")
    base_where = f"WHERE {scope_sql}"
    params = [*scope_args]
    if status:
        base_where += " AND q.status=?"
        params.append(status)
    if customer:
        base_where += " AND c.name LIKE ?"
        params.append(f"%{customer}%")

    total = conn.execute(
        f"SELECT COUNT(*) FROM quotations q LEFT JOIN partners c ON q.partner_id=c.id {base_where}",
        params,
    ).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    sql = f"""
        SELECT q.*, c.name as customer_name
        FROM quotations q
        LEFT JOIN partners c ON q.partner_id=c.id
        {base_where}
        ORDER BY q.id DESC
        LIMIT {PER_PAGE} OFFSET {(page-1)*PER_PAGE}
    """
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["status_label"] = QT_STATUS.get(r["status"], r["status"])
        r["status_class"] = QT_STATUS_CLASS.get(r["status"], "")
    return templates.TemplateResponse(request=request, name="erp/quote_list.html", context={
        "request": request, "page_title": "견적 목록",
        "user_name": u["name"],
        "orders": rows, "status": status, "customer": customer,
        "qt_status": QT_STATUS,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/quotations?status={status}&customer={customer}",
    })


@router.get("/quotations/new", response_class=HTMLResponse)
async def quote_form_new(request: Request, partner_id: int = 0, opp_id: int = 0,
                         u: dict = Depends(require_login), conn=Depends(get_db)):
    book = books.book_of(conn, u)
    customers = [dict(r) for r in conn.execute(
        """SELECT id, name FROM partners WHERE company_id=? AND is_active=1
           AND partner_type IN ('customer','both') ORDER BY name""", (book,)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/quote_form.html", context={
        "request": request, "page_title": "견적서 작성",
        "user_name": u["name"],
        "qt": None, "customers": customers, "pre_partner": partner_id, "opp_id": opp_id,
        "today": today_kst().isoformat(),
    })


@router.get("/quotations/{qt_id}/edit", response_class=HTMLResponse)
async def quote_form_edit(request: Request, qt_id: int,
                          u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "q")
    qt = conn.execute(
        f"SELECT q.* FROM quotations q WHERE q.id=? AND {scope_sql}",
        (qt_id, *scope_args),
    ).fetchone()
    if not qt or qt["status"] != "draft":
        return RedirectResponse("/quotations", status_code=303)
    qt = dict(qt)
    qt["lines"] = [dict(r) for r in conn.execute(
        """SELECT ql.*, i.item_code, i.item_name, i.unit
           FROM quote_lines ql JOIN items i ON ql.item_id=i.id
           WHERE ql.quote_id=? ORDER BY ql.line_no""", (qt_id,)
    ).fetchall()]
    book = books.book_of(conn, u)
    customers = [dict(r) for r in conn.execute(
        """SELECT id, name FROM partners WHERE company_id=? AND is_active=1
           AND partner_type IN ('customer','both') ORDER BY name""", (book,)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/quote_form.html", context={
        "request": request, "page_title": "견적서 수정",
        "user_name": u["name"],
        "qt": qt, "customers": customers,
        "today": today_kst().isoformat(),
    })


@router.post("/quotations/save")
async def quote_save(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    qt_id = int(form.get("qt_id", 0) or 0)
    partner_id = int(form.get("partner_id", 0) or 0)
    quote_date = form.get("quote_date", today_kst().isoformat())
    valid_until = form.get("valid_until", "")
    notes = form.get("notes", "")

    book = books.book_of(conn, u)
    if not partner_id:
        return JSONResponse({"error": "거래처를 선택하세요."}, status_code=400)
    if not conn.execute(
        """SELECT 1 FROM partners WHERE id=? AND company_id=?
           AND partner_type IN ('customer','both')""", (partner_id, book)
    ).fetchone():
        return JSONResponse({"error": "거래처를 찾을 수 없습니다."}, status_code=400)

    contact_id = partner.own_contact(conn, book, partner_id, form.get("contact_id"))
    ship_to = form.get("ship_to", "").strip()

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    total = 0
    for ln in line_nums:
        item_id = int(form.get(f"item_id_{ln}", 0) or 0)
        qty = int(str(form.get(f"qty_{ln}", 0) or 0).replace(",", ""))
        price = int(str(form.get(f"price_{ln}", 0) or 0).replace(",", ""))
        discount = float(form.get(f"discount_{ln}", 0) or 0)
        if item_id and qty > 0 and conn.execute(
            "SELECT 1 FROM items WHERE id=? AND company_id=?", (item_id, book)
        ).fetchone():
            amt = int(qty * price * (1 - discount / 100))
            lines.append((item_id, qty, price, discount, amt))
            total += amt

    if not lines:
        return RedirectResponse("/quotations/new", status_code=303)

    tax = int(total * 0.1)
    is_new = not bool(qt_id)

    try:
        over = partner.guard(conn, book, partner_id, total + tax, quote_date, "견적")
    except ValueError:
        return JSONResponse({"error": "견적일을 확인해 주세요."}, status_code=400)
    if over and (over["block"] or not form.get("credit_ok")):
        return partner.credit_reply(over)

    if qt_id:
        scope_sql, scope_args = erp_scope(conn, u, "quotations")
        existing = conn.execute(
            f"SELECT task_id FROM quotations WHERE id=? AND {scope_sql}", (qt_id, *scope_args)
        ).fetchone()
        if not existing:
            return RedirectResponse("/quotations", status_code=303)
        if task_locked(conn, existing["task_id"]):
            return RedirectResponse(f"/quotations/{qt_id}?error=locked", status_code=303)
        conn.execute(
            """UPDATE quotations SET partner_id=?, quote_date=?, valid_until=?,
               total_amount=?, tax_amount=?, notes=?, contact_id=?, ship_to=? WHERE id=? AND status='draft'""",
            (partner_id or None, quote_date, valid_until, total, tax, notes, contact_id, ship_to, qt_id),
        )
        conn.execute("DELETE FROM quote_lines WHERE quote_id=?", (qt_id,))
    else:
        qt_number, qt_seq = _next_number(conn, "QT", "quotations", "quote_number")
        task_id = stamp_task(conn, request, u["id"], "sales")
        while True:
            try:
                cur = conn.execute(
                    """INSERT INTO quotations (quote_number, partner_id, quote_date, valid_until,
                       total_amount, tax_amount, notes, contact_id, ship_to, created_by, task_id, company_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (qt_number, partner_id or None, quote_date, valid_until, total, tax, notes, contact_id, ship_to,
                     u["id"], task_id, book),
                )
                break
            except sqlite3.IntegrityError:
                qt_seq += 1
                qt_number, _ = _next_number(conn, "QT", "quotations", "quote_number", qt_seq)
        qt_id = cur.lastrowid

    for i, (item_id, qty, price, discount, amt) in enumerate(lines, 1):
        conn.execute(
            "INSERT INTO quote_lines (quote_id, line_no, item_id, quantity, unit_price, discount_rate, amount) VALUES (?,?,?,?,?,?,?)",
            (qt_id, i, item_id, qty, price, discount, amt),
        )

    # 영업기회에서 작성한 견적은 해당 기회에 연결. 발굴 단계면 제안으로 진행
    opp_id = int(form.get("opp_id", 0) or 0)
    if is_new and opp_id:
        conn.execute(
            """UPDATE crm_opps SET quote_id=?, stage=CASE WHEN stage='found' THEN 'proposal' ELSE stage END
               WHERE id=? AND company_id=? AND partner_id=? AND stage NOT IN ('won','lost')""",
            (qt_id, opp_id, book, partner_id),
        )

    if is_new:
        crow = conn.execute("SELECT name FROM partners WHERE id=?", (partner_id,)).fetchone()
        cname = crow["name"] if crow else ""
        log_activity(conn, u["id"], "create", "sales", qt_id, qt_number, f"견적서 작성 {qt_number} ({cname})")
    else:
        qrow = conn.execute("SELECT quote_number FROM quotations WHERE id=?", (qt_id,)).fetchone()
        qt_number = qrow["quote_number"] if qrow else ""
        crow = conn.execute("SELECT name FROM partners WHERE id=?", (partner_id,)).fetchone()
        cname = crow["name"] if crow else ""
        log_activity(conn, u["id"], "update", "sales", qt_id, qt_number, f"견적서 수정 {qt_number} ({cname})")

    conn.commit()
    return RedirectResponse(f"/quotations/{qt_id}", status_code=303)


@router.get("/quotations/{qt_id}", response_class=HTMLResponse)
async def quote_detail(request: Request, qt_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "q")
    qt = conn.execute(
        f"""SELECT q.*, c.name as customer_name,
                  u.name as creator_name, ct.name as contact_name, ct.email as contact_email,
                  COALESCE(NULLIF(ct.mobile, ''), ct.phone) as contact_phone
           FROM quotations q
           LEFT JOIN partners c ON q.partner_id=c.id
           LEFT JOIN users u ON q.created_by=u.id
           LEFT JOIN partner_contacts ct ON ct.id=q.contact_id
           WHERE q.id=? AND {scope_sql}""", (qt_id, *scope_args)
    ).fetchone()
    if not qt:
        return RedirectResponse("/quotations", status_code=303)
    qt = dict(qt)
    if qt["status"] == "sent" and qt["valid_until"] and qt["valid_until"] < today_kst().isoformat():
        conn.execute("UPDATE quotations SET status='expired' WHERE id=?", (qt_id,))
        conn.commit()
        qt["status"] = "expired"
    qt["status_label"] = QT_STATUS.get(qt["status"], qt["status"])
    qt["status_class"] = QT_STATUS_CLASS.get(qt["status"], "")

    lines = [dict(r) for r in conn.execute(
        """SELECT ql.*, i.item_code, i.item_name, i.unit
           FROM quote_lines ql JOIN items i ON ql.item_id=i.id
           WHERE ql.quote_id=? ORDER BY ql.line_no""", (qt_id,)
    ).fetchall()]

    sos = [dict(r) for r in conn.execute(
        "SELECT * FROM sales_orders WHERE quote_id=? ORDER BY id DESC", (qt_id,)
    ).fetchall()]
    for s in sos:
        s["status_label"] = SO_STATUS.get(s["status"], s["status"])
        s["status_class"] = SO_STATUS_CLASS.get(s["status"], "")

    return templates.TemplateResponse(request=request, name="erp/quote_detail.html", context={
        "request": request, "page_title": f"견적서 {qt['quote_number']}",
        "user_name": u["name"],
        "qt": qt, "lines": lines, "sos": sos,
    })


@router.post("/quotations/{qt_id}/send")
async def quote_send(request: Request, qt_id: int,
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "quotations")
    qt = conn.execute(
        f"SELECT status, quote_number FROM quotations WHERE id=? AND {scope_sql}", (qt_id, *scope_args)
    ).fetchone()
    if not qt or qt["status"] != "draft":
        return JSONResponse({"error": "발송할 수 없는 상태입니다."}, status_code=400)
    conn.execute("UPDATE quotations SET status='sent' WHERE id=?", (qt_id,))
    log_activity(conn, u["id"], "send", "sales", qt_id, qt["quote_number"], f"견적서 발송 {qt['quote_number']}")
    conn.commit()
    return RedirectResponse(f"/quotations/{qt_id}", status_code=303)


@router.post("/quotations/{qt_id}/accept")
async def quote_accept(request: Request, qt_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "quotations")
    qt = conn.execute(
        f"SELECT * FROM quotations WHERE id=? AND {scope_sql}", (qt_id, *scope_args)
    ).fetchone()
    if not qt or qt["status"] not in ("draft", "sent"):
        return JSONResponse({"error": "수락할 수 없는 상태입니다."}, status_code=400)
    if qt["valid_until"] and qt["valid_until"] < today_kst().isoformat():
        return JSONResponse({"error": "유효기간이 지난 견적입니다."}, status_code=400)
    prow = conn.execute("SELECT trade_status FROM partners WHERE id=?", (qt["partner_id"],)).fetchone()
    if prow and prow["trade_status"] == "stop":
        return JSONResponse({"error": "거래중지 거래처입니다. 수주를 생성할 수 없습니다."}, status_code=400)

    conn.execute("UPDATE quotations SET status='accepted' WHERE id=?", (qt_id,))
    conn.execute(
        """UPDATE crm_opps SET stage='won', closed_at=? WHERE quote_id=? AND company_id=?
           AND stage NOT IN ('won','lost')""",
        (today_kst().isoformat(), qt_id, qt["company_id"]),
    )

    so_number, so_seq = _next_number(conn, "SO", "sales_orders", "so_number")
    task_id = stamp_task(conn, request, u["id"], "sales")
    while True:
        try:
            cur = conn.execute(
                """INSERT INTO sales_orders (so_number, quote_id, partner_id, order_date,
                   total_amount, tax_amount, notes, contact_id, ship_to, created_by, task_id, company_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (so_number, qt_id, qt["partner_id"], today_kst().isoformat(),
                 qt["total_amount"], qt["tax_amount"], f"견적 {qt['quote_number']} 기반",
                 qt["contact_id"], qt["ship_to"], u["id"], task_id, qt["company_id"]),
            )
            break
        except sqlite3.IntegrityError:
            so_seq += 1
            so_number, _ = _next_number(conn, "SO", "sales_orders", "so_number", so_seq)
    so_id = cur.lastrowid

    qt_lines = conn.execute(
        "SELECT * FROM quote_lines WHERE quote_id=? ORDER BY line_no", (qt_id,)
    ).fetchall()
    for ql in qt_lines:
        conn.execute(
            "INSERT INTO so_lines (so_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,?,?,?,?,?)",
            (so_id, ql["line_no"], ql["item_id"], ql["quantity"], ql["unit_price"], ql["amount"]),
        )

    log_activity(conn, u["id"], "accept", "sales", qt_id, qt["quote_number"], f"견적 수락 {qt['quote_number']}, 수주 {so_number} 자동생성")
    conn.commit()
    return RedirectResponse(f"/sales-orders/{so_id}", status_code=303)


@router.post("/quotations/{qt_id}/reject")
async def quote_reject(request: Request, qt_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "quotations")
    qt = conn.execute(
        f"SELECT status, quote_number FROM quotations WHERE id=? AND {scope_sql}", (qt_id, *scope_args)
    ).fetchone()
    if not qt or qt["status"] not in ("draft", "sent"):
        return JSONResponse({"error": "거절 처리할 수 없는 상태입니다."}, status_code=400)
    conn.execute("UPDATE quotations SET status='rejected' WHERE id=?", (qt_id,))
    log_activity(conn, u["id"], "reject", "sales", qt_id, qt["quote_number"], f"견적 거절 {qt['quote_number']}")
    conn.commit()
    return RedirectResponse(f"/quotations/{qt_id}", status_code=303)


@router.get("/sales-orders", response_class=HTMLResponse)
async def so_list(request: Request, status: str = "", customer: str = "", page: int = 1,
                  u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "so")
    base_where = f"WHERE {scope_sql}"
    params = [*scope_args]
    if status:
        base_where += " AND so.status=?"
        params.append(status)
    if customer:
        base_where += " AND c.name LIKE ?"
        params.append(f"%{customer}%")

    total = conn.execute(
        f"SELECT COUNT(*) FROM sales_orders so LEFT JOIN partners c ON so.partner_id=c.id {base_where}",
        params,
    ).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    sql = f"""
        SELECT so.*, c.name as customer_name
        FROM sales_orders so
        LEFT JOIN partners c ON so.partner_id=c.id
        {base_where}
        ORDER BY so.id DESC
        LIMIT {PER_PAGE} OFFSET {(page-1)*PER_PAGE}
    """
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["status_label"] = SO_STATUS.get(r["status"], r["status"])
        r["status_class"] = SO_STATUS_CLASS.get(r["status"], "")
    return templates.TemplateResponse(request=request, name="erp/so_list.html", context={
        "request": request, "page_title": "수주 목록",
        "user_name": u["name"],
        "orders": rows, "status": status, "customer": customer,
        "so_status": SO_STATUS,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/sales-orders?status={status}&customer={customer}",
    })


@router.get("/sales-orders/unshipped", response_class=HTMLResponse)
async def so_unshipped(request: Request, q: str = "", overdue: int = 0,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "so")
    where = f"WHERE {scope_sql} AND so.status IN ('confirmed','picking') AND sl.quantity > sl.shipped_qty - sl.returned_qty"
    params = [*scope_args]
    if q:
        where += " AND (p.name LIKE ? OR i.item_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if overdue:
        where += " AND so.delivery_date < ?"
        params.append(today_kst().isoformat())
    rows = [dict(r) for r in conn.execute(
        f"""SELECT so.id AS doc_id, so.so_number AS doc_no, so.order_date AS doc_date, so.delivery_date, p.name AS partner,
                   i.item_code, i.item_name, sl.quantity, sl.shipped_qty AS done, sl.returned_qty, sl.unit_price
            FROM so_lines sl JOIN sales_orders so ON so.id=sl.so_id JOIN items i ON i.id=sl.item_id
            LEFT JOIN partners p ON p.id=so.partner_id
            {where} ORDER BY so.delivery_date, so.id, sl.line_no""",
        params,
    ).fetchall()]
    for r in rows:
        r["remain"] = r["quantity"] - r["done"] + r["returned_qty"]
        r["amt"] = r["remain"] * r["unit_price"]
    return templates.TemplateResponse(request=request, name="erp/backlog.html", context={
        "request": request, "page_title": "미출고 현황", "user_name": u["name"],
        "rows": rows, "q": q, "overdue": overdue, "today": today_kst().isoformat(),
        "total_qty": sum(r["remain"] for r in rows), "total_amt": sum(r["amt"] for r in rows),
        "base": "/sales-orders", "label": "출고",
    })


@router.get("/sales-orders/{so_id}", response_class=HTMLResponse)
async def so_detail(request: Request, so_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "so")
    so = conn.execute(
        f"""SELECT so.*, c.name as customer_name,
                  u.name as creator_name, q.quote_number, ct.name as contact_name, ct.email as contact_email,
                  COALESCE(NULLIF(ct.mobile, ''), ct.phone) as contact_phone
           FROM sales_orders so
           LEFT JOIN partners c ON so.partner_id=c.id
           LEFT JOIN users u ON so.created_by=u.id
           LEFT JOIN quotations q ON so.quote_id=q.id
           LEFT JOIN partner_contacts ct ON ct.id=so.contact_id
           WHERE so.id=? AND {scope_sql}""", (so_id, *scope_args)
    ).fetchone()
    if not so:
        return RedirectResponse("/sales-orders", status_code=303)
    so = dict(so)
    so["status_label"] = SO_STATUS.get(so["status"], so["status"])
    so["status_class"] = SO_STATUS_CLASS.get(so["status"], "")

    lines = [dict(r) for r in conn.execute(
        """SELECT sl.*, i.item_code, i.item_name, i.unit
           FROM so_lines sl JOIN items i ON sl.item_id=i.id
           WHERE sl.so_id=? ORDER BY sl.line_no""", (so_id,)
    ).fetchall()]

    ships = [dict(r) for r in conn.execute(
        """SELECT s.*, w.name as warehouse_name, ti.id AS inv_id, ti.total AS inv_total, d.id AS doc_id, d.slip_no
           FROM shipments s
           LEFT JOIN warehouses w ON s.warehouse_id=w.id
           LEFT JOIN tax_invoices ti ON ti.source_type='ship' AND ti.source_id=s.id
           LEFT JOIN erp_docs d ON d.source_type='ship' AND d.source_id=s.id
           WHERE s.so_id=? ORDER BY s.id DESC""", (so_id,)
    ).fetchall()]
    for s in ships:
        s["status_label"] = SHIP_STATUS.get(s["status"], s["status"])

    return templates.TemplateResponse(request=request, name="erp/so_detail.html", context={
        "request": request, "page_title": f"수주 {so['so_number']}",
        "user_name": u["name"],
        "so": so, "lines": lines, "ships": ships,
    })


@router.post("/sales-orders/{so_id}/cancel")
async def so_cancel(request: Request, so_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "sales_orders")
    so = conn.execute(
        f"SELECT status, so_number, task_id FROM sales_orders WHERE id=? AND {scope_sql}", (so_id, *scope_args)
    ).fetchone()
    if not so or so["status"] not in ("confirmed",):
        return JSONResponse({"error": "취소할 수 없는 상태입니다."}, status_code=400)
    if task_locked(conn, so["task_id"]):
        return JSONResponse({"error": "승인된 태스크의 수주는 취소할 수 없습니다"}, status_code=403)
    conn.execute("UPDATE sales_orders SET status='cancelled' WHERE id=?", (so_id,))
    log_activity(conn, u["id"], "cancel", "sales", so_id, so["so_number"], f"수주 취소 {so['so_number']}")
    conn.commit()
    return RedirectResponse(f"/sales-orders/{so_id}", status_code=303)


@router.get("/shipments/new", response_class=HTMLResponse)
async def ship_form_new(request: Request, so_id: int = 0,
                        u: dict = Depends(require_login), conn=Depends(get_db)):
    so = None
    so_lines = []
    if so_id:
        scope_sql, scope_args = erp_scope(conn, u, "so")
        so = conn.execute(
            f"""SELECT so.*, c.name as customer_name
               FROM sales_orders so
               LEFT JOIN partners c ON so.partner_id=c.id
               WHERE so.id=? AND so.status IN ('confirmed','picking') AND {scope_sql}""", (so_id, *scope_args)
        ).fetchone()
        if so:
            so = dict(so)
            so_lines = [dict(r) for r in conn.execute(
                """SELECT sl.*, i.item_code, i.item_name, i.unit,
                          (sl.quantity - sl.shipped_qty + sl.returned_qty) as remaining_qty
                   FROM so_lines sl JOIN items i ON sl.item_id=i.id
                   WHERE sl.so_id=? AND sl.quantity > sl.shipped_qty - sl.returned_qty
                   ORDER BY sl.line_no""", (so_id,)
            ).fetchall()]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code",
        (books.book_of(conn, u),)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/ship_form.html", context={
        "request": request, "page_title": "출고 등록",
        "user_name": u["name"],
        "so": so, "so_lines": so_lines, "warehouses": warehouses,
        "today": today_kst().isoformat(),
    })


@router.post("/shipments/save")
async def ship_save(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    so_id = int(form.get("so_id", 0) or 0)
    warehouse_id = int(form.get("warehouse_id", 0) or 0)
    ship_date = form.get("ship_date", today_kst().isoformat())
    notes = form.get("notes", "")

    book = books.book_of(conn, u)
    so = None
    if so_id:
        scope_sql, scope_args = erp_scope(conn, u, "so")
        so = conn.execute(
            f"SELECT company_id, partner_id, so_number FROM sales_orders so WHERE so.id=? AND {scope_sql}",
            (so_id, *scope_args),
        ).fetchone()
        if not so:
            return RedirectResponse("/sales-orders", status_code=303)

    cid = so["company_id"] if so else book
    if not warehouse_id or not conn.execute(
        "SELECT 1 FROM warehouses WHERE id=? AND company_id=?", (warehouse_id, cid)
    ).fetchone():
        return JSONResponse({"error": "출고 창고를 선택해 주세요."}, status_code=400)

    contact_id = partner.own_contact(conn, cid, so["partner_id"] if so else 0, form.get("contact_id"))
    ship_to = form.get("ship_to", "").strip()

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    for ln in line_nums:
        so_line_id = int(form.get(f"so_line_id_{ln}", 0) or 0)
        item_id = int(form.get(f"item_id_{ln}", 0) or 0)
        ship_qty = int(str(form.get(f"ship_qty_{ln}", 0) or 0).replace(",", ""))
        if so_line_id:
            # 수주 라인은 해당 수주 소속만 허용, 잔량 초과 출고 차단
            sl = conn.execute(
                """SELECT sl.item_id, sl.quantity - sl.shipped_qty + sl.returned_qty AS remain, i.item_name
                   FROM so_lines sl JOIN items i ON i.id=sl.item_id WHERE sl.id=? AND sl.so_id=?""",
                (so_line_id, so_id),
            ).fetchone()
            if not sl:
                continue
            if ship_qty > sl["remain"]:
                return JSONResponse({"error": f"수주 잔량 초과: {sl['item_name']} (잔량 {sl['remain']}, 출고 {ship_qty})"},
                                    status_code=400)
            item_id = sl["item_id"]
        if item_id and ship_qty > 0 and conn.execute(
            "SELECT 1 FROM items WHERE id=? AND company_id=?", (item_id, cid)
        ).fetchone():
            lines.append((so_line_id, item_id, ship_qty))

    if not lines:
        return JSONResponse({"error": "출고 수량을 입력해 주세요."}, status_code=400)

    if so:
        supply = sum(qty * conn.execute("SELECT unit_price FROM so_lines WHERE id=?", (sid,)).fetchone()[0]
                     for sid, _, qty in lines if sid)
        try:
            over = partner.guard(conn, cid, so["partner_id"], supply + invoices.terms(conn, so["partner_id"], supply)[2],
                                 ship_date, "출고")
        except ValueError:
            return JSONResponse({"error": "출고일을 확인해 주세요."}, status_code=400)
        if over and (over["block"] or not form.get("credit_ok")):
            return partner.credit_reply(over)

    uid = u["id"]
    ship_number, ship_seq = _next_number(conn, "SH", "shipments", "ship_number")
    task_id = stamp_task(conn, request, uid, "sales")

    while True:
        try:
            cur = conn.execute(
                """INSERT INTO shipments (ship_number, so_id, warehouse_id, ship_date, status, notes,
                   contact_id, ship_to, created_by, task_id, company_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (ship_number, so_id or None, warehouse_id, ship_date, "confirmed", notes,
                 contact_id, ship_to, uid, task_id, cid),
            )
            break
        except sqlite3.IntegrityError:
            ship_seq += 1
            ship_number, _ = _next_number(conn, "SH", "shipments", "ship_number", ship_seq)
    ship_id = cur.lastrowid

    total_amount = 0
    cogs = 0
    inv_items = []
    for so_line_id, item_id, ship_qty in lines:
        conn.execute(
            "INSERT INTO ship_lines (ship_id, so_line_id, item_id, shipped_qty) VALUES (?,?,?,?)",
            (ship_id, so_line_id or None, item_id, ship_qty),
        )

        try:
            cogs += stock.move_out(conn, item_id, warehouse_id, ship_qty, ship_date, "ship", ship_id, uid)
        except ValueError as e:
            conn.rollback()
            return JSONResponse({"error": str(e)}, status_code=400)

        if so_line_id:
            conn.execute(
                "UPDATE so_lines SET shipped_qty = shipped_qty + ? WHERE id=?",
                (ship_qty, so_line_id),
            )
            sl = conn.execute(
                "SELECT sl.unit_price, i.item_name FROM so_lines sl JOIN items i ON sl.item_id=i.id WHERE sl.id=?",
                (so_line_id,),
            ).fetchone()
            if sl:
                total_amount += ship_qty * sl["unit_price"]
                inv_items.append({"name": sl["item_name"], "qty": ship_qty, "unit_price": sl["unit_price"],
                                  "supply_amt": ship_qty * sl["unit_price"]})

    if so_id:
        if conn.execute("SELECT 1 FROM so_lines WHERE so_id=? AND shipped_qty - returned_qty > quantity",
                       (so_id,)).fetchone():
            conn.rollback()
            return JSONResponse({"error": "수주 잔량을 초과하는 출고가 있습니다."}, status_code=400)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM so_lines WHERE so_id=? AND quantity > shipped_qty - returned_qty",
            (so_id,),
        ).fetchone()[0]
        if remaining == 0:
            conn.execute("UPDATE sales_orders SET status='shipped' WHERE id=?", (so_id,))
        else:
            so_row = conn.execute("SELECT status FROM sales_orders WHERE id=?", (so_id,)).fetchone()
            if so_row and so_row["status"] == "confirmed":
                conn.execute("UPDATE sales_orders SET status='picking' WHERE id=?", (so_id,))

    partner_id = so["partner_id"] if so else None

    if total_amount > 0 or cogs > 0:
        try:
            _create_ship_slip(conn, book, ship_id, ship_number, total_amount, uid, ship_date, partner_id, inv_items,
                              cogs)
        except ValueError as e:
            conn.rollback()
            return JSONResponse({"error": str(e)}, status_code=400)

    so_number_str = so["so_number"] if so else ""
    log_activity(conn, u["id"], "create", "sales", ship_id, ship_number, f"출고 등록 {ship_number} (SO: {so_number_str})")
    audit.log(conn, u["id"], "ship_confirm", "shipment", ship_id, ship_number, company_id=cid)

    conn.commit()
    return RedirectResponse(f"/shipments/{ship_id}", status_code=303)


def _create_ship_slip(conn, book, ship_id, ship_number, amount, uid, ship_date, partner_id, items=(), cogs=0):
    summary = f"출고 {ship_number}"
    inv, lines = None, []
    if amount:
        tax_type, evidence, vat = invoices.terms(conn, partner_id, amount)
        inv = {"kind": "매출", "tax_type": tax_type, "evidence": evidence, "issue_date": ship_date,
               "partner_id": partner_id, "supply_amt": amount, "vat": vat, "source_type": "ship", "source_id": ship_id}
        lines = invoices.inv_lines(inv, "401", "110", summary)
    if cogs:
        lines += [{"code": "451", "debit": cogs, "credit": 0, "summary": f"{summary} 매출원가"},
                  {"code": "120", "debit": 0, "credit": cogs, "summary": f"{summary} 매출원가"}]
    doc_id = books.post(conn, book, uid, ship_date, lines, f"매출 전표 ({ship_number})", "ship", ship_id,
                        content=f"출고번호 {ship_number} 자동 생성 전표")
    if inv:
        invoices.add(conn, book, uid, {**inv, "doc_id": doc_id}, items)
    return doc_id


@router.get("/shipments/{ship_id}", response_class=HTMLResponse)
async def ship_detail(request: Request, ship_id: int,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "s")
    ship = conn.execute(
        f"""SELECT s.*, w.name as warehouse_name, u.name as creator_name,
                  so.so_number, c.name as customer_name, ct.name as contact_name, ct.email as contact_email,
                  COALESCE(NULLIF(ct.mobile, ''), ct.phone) as contact_phone
           FROM shipments s
           LEFT JOIN warehouses w ON s.warehouse_id=w.id
           LEFT JOIN users u ON s.created_by=u.id
           LEFT JOIN sales_orders so ON s.so_id=so.id
           LEFT JOIN partners c ON so.partner_id=c.id
           LEFT JOIN partner_contacts ct ON ct.id=s.contact_id
           WHERE s.id=? AND {scope_sql}""", (ship_id, *scope_args)
    ).fetchone()
    if not ship:
        return RedirectResponse("/sales-orders", status_code=303)
    ship = dict(ship)
    ship["status_label"] = SHIP_STATUS.get(ship["status"], ship["status"])

    lines = [dict(r) for r in conn.execute(
        """SELECT sl.*, i.item_code, i.item_name, i.unit
           FROM ship_lines sl JOIN items i ON sl.item_id=i.id
           WHERE sl.ship_id=? ORDER BY sl.id""", (ship_id,)
    ).fetchall()]

    can_return = False
    return_hist = []
    if ship["kind"] == "반품":
        orig = conn.execute(
            """SELECT os.id, os.ship_number FROM ship_lines l JOIN ship_lines ol ON ol.id=l.orig_line_id
               JOIN shipments os ON os.id=ol.ship_id WHERE l.ship_id=? LIMIT 1""", (ship_id,)
        ).fetchone()
        ship["orig_ship_id"] = orig["id"] if orig else None
        ship["orig_ship_number"] = orig["ship_number"] if orig else None
    else:
        if ship["status"] == "confirmed":
            can_return = sum(returns.limits(conn, ship["company_id"], "ship", ship_id).values()) > 0
        return_hist = [dict(r) for r in conn.execute(
            """SELECT rs.id, rs.ship_number, rs.ship_date, rs.canceled_at, SUM(rl.shipped_qty) AS qty
               FROM ship_lines rl JOIN shipments rs ON rs.id=rl.ship_id
               WHERE rl.orig_line_id IN (SELECT id FROM ship_lines WHERE ship_id=?)
               GROUP BY rs.id ORDER BY rs.id DESC""", (ship_id,)
        ).fetchall()]

    return templates.TemplateResponse(request=request, name="erp/ship_detail.html", context={
        "request": request, "page_title": f"출고 {ship['ship_number']}",
        "user_name": u["name"], "can_edit": partner.can_edit(u),
        "ship": ship, "lines": lines, "can_return": can_return, "return_hist": return_hist,
    })


@router.get("/shipments/{ship_id}/return", response_class=HTMLResponse)
async def ship_return_form(request: Request, ship_id: int,
                           u: dict = Depends(require_login), conn=Depends(get_db)):
    book = books.book_of(conn, u)
    try:
        cap = returns.limits(conn, book, "ship", ship_id)
    except LookupError:
        raise HTTPException(status_code=404)
    ship = conn.execute("SELECT ship_number FROM shipments WHERE id=?", (ship_id,)).fetchone()
    lines = [dict(r) for r in conn.execute(
        """SELECT l.id, l.shipped_qty AS orig_qty, i.item_code, i.item_name, i.unit
           FROM ship_lines l JOIN items i ON i.id=l.item_id
           WHERE l.ship_id=? ORDER BY l.id""", (ship_id,)
    ).fetchall()]
    for l in lines:
        l["cap"] = cap.get(l["id"], 0)
    return templates.TemplateResponse(request=request, name="erp/return_form.html", context={
        "request": request, "page_title": f"출고 반품 ({ship['ship_number']})",
        "user_name": u["name"], "typ": "ship", "doc_number": ship["ship_number"],
        "action": f"/shipments/{ship_id}/return", "back": f"/shipments/{ship_id}",
        "lines": lines, "today": today_kst().isoformat(),
    })


@router.post("/shipments/{ship_id}/return")
async def ship_return_save(request: Request, ship_id: int,
                           u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    book = books.book_of(conn, u)
    ret_date = form.get("ret_date", today_kst().isoformat())
    notes = form.get("notes", "")
    try:
        cap = returns.limits(conn, book, "ship", ship_id)
    except LookupError:
        raise HTTPException(status_code=404)
    qtys = {}
    for lid in cap:
        qty = int(str(form.get(f"qty_{lid}", 0) or 0).replace(",", "") or 0)
        if qty:
            qtys[lid] = qty

    number, seq = _next_number(conn, "SH", "shipments", "ship_number")
    while True:
        try:
            ret_id = returns.create(conn, book, u["id"], "ship", ship_id, ret_date, qtys, notes, number)
            break
        except sqlite3.IntegrityError:
            seq += 1
            number, _ = _next_number(conn, "SH", "shipments", "ship_number", seq)
        except LookupError:
            raise HTTPException(status_code=404)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    log_activity(conn, u["id"], "create", "sales", ret_id, number, f"출고 반품 등록 {number} (출고 {ship_id})")
    conn.commit()
    return RedirectResponse(f"/shipments/{ret_id}", status_code=303)


@router.delete("/shipments/{ship_id}")
async def ship_return_cancel(ship_id: int, u: dict = Depends(partner.require_editor), conn=Depends(get_db)):
    ship = conn.execute("SELECT kind, ship_number FROM shipments WHERE id=? AND company_id=?",
                        (ship_id, u["book"])).fetchone()
    if not ship or ship["kind"] != "반품":
        raise HTTPException(status_code=404)
    try:
        returns.cancel(conn, u["book"], u["id"], "ship", ship_id)
    except LookupError:
        raise HTTPException(status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    log_activity(conn, u["id"], "cancel", "sales", ship_id, ship["ship_number"], f"출고 반품 취소 {ship['ship_number']}")
    conn.commit()
    return JSONResponse({"ok": True})


@router.get("/sales-orders/{so_id}/statement", response_class=HTMLResponse)
async def so_statement(request: Request, so_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "so")
    so = conn.execute(
        f"""SELECT so.*, c.name as customer_name, c.biz_no as customer_biz_no,
                  c.representative as customer_rep, c.address as customer_addr,
                  ct.name as contact_name, COALESCE(NULLIF(ct.mobile, ''), ct.phone) as contact_phone
           FROM sales_orders so
           LEFT JOIN partners c ON so.partner_id=c.id
           LEFT JOIN partner_contacts ct ON ct.id=so.contact_id
           WHERE so.id=? AND {scope_sql}""", (so_id, *scope_args)
    ).fetchone()
    if not so:
        return RedirectResponse("/sales-orders", status_code=303)

    lines = [dict(r) for r in conn.execute(
        """SELECT sl.*, i.item_code, i.item_name, i.unit
           FROM so_lines sl JOIN items i ON sl.item_id=i.id
           WHERE sl.so_id=? ORDER BY sl.line_no""", (so_id,)
    ).fetchall()]

    book = books.book_of(conn, u) or books.INTERNAL
    return templates.TemplateResponse(request=request, name="erp/trade_statement.html", context={
        "request": request, "doc_type": "sales",
        "doc_number": so["so_number"], "doc_date": so["order_date"],
        "supplier": books.company_info(conn, book),
        "buyer": {
            "name": so["customer_name"] or "", "biz_no": so["customer_biz_no"] or "",
            "representative": so["customer_rep"] or "", "address": so["customer_addr"] or "",
        },
        "contact_name": so["contact_name"] or "", "contact_phone": so["contact_phone"] or "",
        "ship_to": so["ship_to"] or "",
        "lines": lines,
        "total_amount": so["total_amount"], "tax_amount": so["tax_amount"],
    })
