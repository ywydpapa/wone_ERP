import sqlite3
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.constants import COMPANY_INFO
from core.task_link import stamp_task, erp_scope, task_locked
from core.deps import get_db, require_login, templates
from core.erp_log import log_activity
from core.tz import today_kst

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
        f"SELECT COUNT(*) FROM quotations q LEFT JOIN client_companies c ON q.customer_id=c.id {base_where}",
        params,
    ).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    sql = f"""
        SELECT q.*, c.name as customer_name
        FROM quotations q
        LEFT JOIN client_companies c ON q.customer_id=c.id
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
async def quote_form_new(request: Request,
                         u: dict = Depends(require_login), conn=Depends(get_db)):
    customers = [dict(r) for r in conn.execute(
        "SELECT id, name FROM client_companies WHERE status='active' ORDER BY name"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/quote_form.html", context={
        "request": request, "page_title": "견적서 작성",
        "user_name": u["name"],
        "qt": None, "customers": customers,
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
    customers = [dict(r) for r in conn.execute(
        "SELECT id, name FROM client_companies WHERE status='active' ORDER BY name"
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
    customer_id = int(form.get("customer_id", 0) or 0)
    quote_date = form.get("quote_date", today_kst().isoformat())
    valid_until = form.get("valid_until", "")
    notes = form.get("notes", "")

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    total = 0
    for ln in line_nums:
        item_id = int(form.get(f"item_id_{ln}", 0) or 0)
        qty = int(form.get(f"qty_{ln}", 0) or 0)
        price = int(form.get(f"price_{ln}", 0) or 0)
        discount = float(form.get(f"discount_{ln}", 0) or 0)
        if item_id and qty > 0:
            amt = int(qty * price * (1 - discount / 100))
            lines.append((item_id, qty, price, discount, amt))
            total += amt

    if not lines:
        return RedirectResponse("/quotations/new", status_code=303)

    tax = int(total * 0.1)
    is_new = not bool(qt_id)

    if qt_id:
        existing = conn.execute("SELECT task_id FROM quotations WHERE id=?", (qt_id,)).fetchone()
        if existing and task_locked(conn, existing["task_id"]):
            return RedirectResponse(f"/quotations/{qt_id}?error=locked", status_code=303)
        conn.execute(
            """UPDATE quotations SET customer_id=?, quote_date=?, valid_until=?,
               total_amount=?, tax_amount=?, notes=? WHERE id=? AND status='draft'""",
            (customer_id or None, quote_date, valid_until, total, tax, notes, qt_id),
        )
        conn.execute("DELETE FROM quote_lines WHERE quote_id=?", (qt_id,))
    else:
        qt_number, qt_seq = _next_number(conn, "QT", "quotations", "quote_number")
        task_id = stamp_task(conn, request, u["id"], "sales")
        while True:
            try:
                cur = conn.execute(
                    """INSERT INTO quotations (quote_number, customer_id, quote_date, valid_until,
                       total_amount, tax_amount, notes, created_by, task_id)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (qt_number, customer_id or None, quote_date, valid_until, total, tax, notes, u["id"], task_id),
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

    if is_new:
        crow = conn.execute("SELECT name FROM client_companies WHERE id=?", (customer_id,)).fetchone()
        cname = crow["name"] if crow else ""
        log_activity(conn, u["id"], "create", "sales", qt_id, qt_number, f"견적서 작성 {qt_number} ({cname})")
    else:
        qrow = conn.execute("SELECT quote_number FROM quotations WHERE id=?", (qt_id,)).fetchone()
        qt_number = qrow["quote_number"] if qrow else ""
        crow = conn.execute("SELECT name FROM client_companies WHERE id=?", (customer_id,)).fetchone()
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
                  u.name as creator_name
           FROM quotations q
           LEFT JOIN client_companies c ON q.customer_id=c.id
           LEFT JOIN users u ON q.created_by=u.id
           WHERE q.id=? AND {scope_sql}""", (qt_id, *scope_args)
    ).fetchone()
    if not qt:
        return RedirectResponse("/quotations", status_code=303)
    qt = dict(qt)
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
    qt = conn.execute("SELECT status, quote_number FROM quotations WHERE id=?", (qt_id,)).fetchone()
    if not qt or qt["status"] != "draft":
        return JSONResponse({"error": "발송할 수 없는 상태입니다."}, status_code=400)
    conn.execute("UPDATE quotations SET status='sent' WHERE id=?", (qt_id,))
    log_activity(conn, u["id"], "send", "sales", qt_id, qt["quote_number"], f"견적서 발송 {qt['quote_number']}")
    conn.commit()
    return RedirectResponse(f"/quotations/{qt_id}", status_code=303)


@router.post("/quotations/{qt_id}/accept")
async def quote_accept(request: Request, qt_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    qt = conn.execute("SELECT * FROM quotations WHERE id=?", (qt_id,)).fetchone()
    if not qt or qt["status"] not in ("draft", "sent"):
        return JSONResponse({"error": "수락할 수 없는 상태입니다."}, status_code=400)

    conn.execute("UPDATE quotations SET status='accepted' WHERE id=?", (qt_id,))

    so_number, so_seq = _next_number(conn, "SO", "sales_orders", "so_number")
    task_id = stamp_task(conn, request, u["id"], "sales")
    while True:
        try:
            cur = conn.execute(
                """INSERT INTO sales_orders (so_number, quote_id, customer_id, order_date,
                   total_amount, tax_amount, notes, created_by, task_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (so_number, qt_id, qt["customer_id"], today_kst().isoformat(),
                 qt["total_amount"], qt["tax_amount"], f"견적 {qt['quote_number']} 기반", u["id"], task_id),
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
    qt = conn.execute("SELECT status, quote_number FROM quotations WHERE id=?", (qt_id,)).fetchone()
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
        f"SELECT COUNT(*) FROM sales_orders so LEFT JOIN client_companies c ON so.customer_id=c.id {base_where}",
        params,
    ).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    sql = f"""
        SELECT so.*, c.name as customer_name
        FROM sales_orders so
        LEFT JOIN client_companies c ON so.customer_id=c.id
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


@router.get("/sales-orders/{so_id}", response_class=HTMLResponse)
async def so_detail(request: Request, so_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "so")
    so = conn.execute(
        f"""SELECT so.*, c.name as customer_name,
                  u.name as creator_name, q.quote_number
           FROM sales_orders so
           LEFT JOIN client_companies c ON so.customer_id=c.id
           LEFT JOIN users u ON so.created_by=u.id
           LEFT JOIN quotations q ON so.quote_id=q.id
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
        """SELECT s.*, w.name as warehouse_name
           FROM shipments s
           LEFT JOIN warehouses w ON s.warehouse_id=w.id
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
    so = conn.execute("SELECT status, so_number, task_id FROM sales_orders WHERE id=?", (so_id,)).fetchone()
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
        so = conn.execute(
            """SELECT so.*, c.name as customer_name
               FROM sales_orders so
               LEFT JOIN client_companies c ON so.customer_id=c.id
               WHERE so.id=? AND so.status IN ('confirmed','picking')""", (so_id,)
        ).fetchone()
        if so:
            so = dict(so)
            so_lines = [dict(r) for r in conn.execute(
                """SELECT sl.*, i.item_code, i.item_name, i.unit,
                          (sl.quantity - sl.shipped_qty) as remaining_qty
                   FROM so_lines sl JOIN items i ON sl.item_id=i.id
                   WHERE sl.so_id=? AND sl.quantity > sl.shipped_qty
                   ORDER BY sl.line_no""", (so_id,)
            ).fetchall()]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE is_active=1 ORDER BY code"
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

    if not warehouse_id:
        return RedirectResponse(f"/shipments/new?so_id={so_id}", status_code=303)

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    for ln in line_nums:
        so_line_id = int(form.get(f"so_line_id_{ln}", 0) or 0)
        item_id = int(form.get(f"item_id_{ln}", 0) or 0)
        ship_qty = int(form.get(f"ship_qty_{ln}", 0) or 0)
        if item_id and ship_qty > 0:
            lines.append((so_line_id, item_id, ship_qty))

    if not lines:
        return RedirectResponse(f"/shipments/new?so_id={so_id}", status_code=303)

    for _, item_id, ship_qty in lines:
        stk = conn.execute(
            "SELECT quantity FROM stock WHERE item_id=? AND warehouse_id=?",
            (item_id, warehouse_id),
        ).fetchone()
        avail = stk["quantity"] if stk else 0
        if avail < ship_qty:
            item = conn.execute("SELECT name FROM items WHERE id=?", (item_id,)).fetchone()
            msg = f"재고 부족: {item['name']} (재고 {avail}, 출고 {ship_qty})"
            return RedirectResponse(
                f"/shipments/new?so_id={so_id}&error={quote(msg)}",
                status_code=303,
            )

    uid = u["id"]
    ship_number, ship_seq = _next_number(conn, "SH", "shipments", "ship_number")
    task_id = stamp_task(conn, request, uid, "sales")

    while True:
        try:
            cur = conn.execute(
                """INSERT INTO shipments (ship_number, so_id, warehouse_id, ship_date, status, notes, created_by, task_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ship_number, so_id or None, warehouse_id, ship_date, "confirmed", notes, uid, task_id),
            )
            break
        except sqlite3.IntegrityError:
            ship_seq += 1
            ship_number, _ = _next_number(conn, "SH", "shipments", "ship_number", ship_seq)
    ship_id = cur.lastrowid

    total_amount = 0
    for so_line_id, item_id, ship_qty in lines:
        conn.execute(
            "INSERT INTO ship_lines (ship_id, so_line_id, item_id, shipped_qty) VALUES (?,?,?,?)",
            (ship_id, so_line_id or None, item_id, ship_qty),
        )

        existing = conn.execute(
            "SELECT id, quantity FROM stock WHERE item_id=? AND warehouse_id=?",
            (item_id, warehouse_id),
        ).fetchone()
        if existing:
            new_qty = max(0, existing["quantity"] - ship_qty)
            conn.execute("UPDATE stock SET quantity=? WHERE id=?", (new_qty, existing["id"]))
        else:
            new_qty = 0

        conn.execute(
            """INSERT INTO stock_transactions (item_id, warehouse_id, trans_date, trans_type,
               quantity, ref_type, ref_id, balance_qty, created_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (item_id, warehouse_id, ship_date, "out", ship_qty, "ship", ship_id, new_qty, uid),
        )

        if so_line_id:
            conn.execute(
                "UPDATE so_lines SET shipped_qty = shipped_qty + ? WHERE id=?",
                (ship_qty, so_line_id),
            )
            sl = conn.execute("SELECT unit_price FROM so_lines WHERE id=?", (so_line_id,)).fetchone()
            if sl:
                total_amount += ship_qty * sl["unit_price"]

    if so_id:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM so_lines WHERE so_id=? AND quantity > shipped_qty",
            (so_id,),
        ).fetchone()[0]
        if remaining == 0:
            conn.execute("UPDATE sales_orders SET status='shipped' WHERE id=?", (so_id,))
        else:
            so_row = conn.execute("SELECT status FROM sales_orders WHERE id=?", (so_id,)).fetchone()
            if so_row and so_row["status"] == "confirmed":
                conn.execute("UPDATE sales_orders SET status='picking' WHERE id=?", (so_id,))

    customer_name = ""
    if so_id:
        c_row = conn.execute(
            "SELECT c.name FROM client_companies c JOIN sales_orders so ON so.customer_id=c.id WHERE so.id=?",
            (so_id,),
        ).fetchone()
        if c_row:
            customer_name = c_row["name"]

    if total_amount > 0:
        try:
            _create_ship_slip(conn, ship_id, ship_number, total_amount, uid, ship_date, customer_name)
        except ValueError:
            so_number_str = ""
            if so_id:
                so_row = conn.execute("SELECT so_number FROM sales_orders WHERE id=?", (so_id,)).fetchone()
                if so_row:
                    so_number_str = so_row["so_number"]
            log_activity(conn, u["id"], "create", "sales", ship_id, ship_number, f"출고 등록 {ship_number} (SO: {so_number_str})")
            conn.commit()
            return RedirectResponse(f"/shipments/{ship_id}?error=period_closed", status_code=303)

    so_number_str = ""
    if so_id:
        so_row = conn.execute("SELECT so_number FROM sales_orders WHERE id=?", (so_id,)).fetchone()
        if so_row:
            so_number_str = so_row["so_number"]
    log_activity(conn, u["id"], "create", "sales", ship_id, ship_number, f"출고 등록 {ship_number} (SO: {so_number_str})")

    conn.commit()
    return RedirectResponse(f"/shipments/{ship_id}", status_code=303)


def _create_ship_slip(conn, ship_id, ship_number, amount, uid, ship_date, partner_name):
    y, m = int(ship_date[:4]), int(ship_date[5:7])
    closed = conn.execute(
        "SELECT 1 FROM fi_closings WHERE year=? AND month=? AND status='closed'", [y, m]
    ).fetchone()
    if closed:
        raise ValueError("마감된 회계기간")

    title = f"매출 전표 ({ship_number})"
    cur = conn.execute(
        """INSERT INTO erp_docs (user_id, doc_type, title, content, status, slip_type, slip_date, slip_total)
           VALUES (?,?,?,?,?,?,?,?)""",
        (uid, "expense", title, f"출고번호 {ship_number} 자동 생성 전표", "done", "대체", ship_date, amount),
    )
    doc_id = cur.lastrowid
    year = today_kst().year
    doc_number = f"SAL-{year}-{doc_id:04d}"
    conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, doc_id))

    conn.execute(
        "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
        (doc_id, 1, "[110] 외상매출금", "110", amount, 0, partner_name, f"출고 {ship_number}"),
    )
    conn.execute(
        "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
        (doc_id, 2, "[401] 상품매출", "401", 0, amount, partner_name, f"출고 {ship_number}"),
    )


@router.get("/shipments/{ship_id}", response_class=HTMLResponse)
async def ship_detail(request: Request, ship_id: int,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "s")
    ship = conn.execute(
        f"""SELECT s.*, w.name as warehouse_name, u.name as creator_name,
                  so.so_number, c.name as customer_name
           FROM shipments s
           LEFT JOIN warehouses w ON s.warehouse_id=w.id
           LEFT JOIN users u ON s.created_by=u.id
           LEFT JOIN sales_orders so ON s.so_id=so.id
           LEFT JOIN client_companies c ON so.customer_id=c.id
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

    return templates.TemplateResponse(request=request, name="erp/ship_detail.html", context={
        "request": request, "page_title": f"출고 {ship['ship_number']}",
        "user_name": u["name"],
        "ship": ship, "lines": lines,
    })


@router.get("/sales-orders/{so_id}/statement", response_class=HTMLResponse)
async def so_statement(request: Request, so_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    so = conn.execute(
        """SELECT so.*, c.name as customer_name, c.biz_no as customer_biz_no,
                  c.representative as customer_rep, c.address as customer_addr
           FROM sales_orders so
           LEFT JOIN client_companies c ON so.customer_id=c.id
           WHERE so.id=?""", (so_id,)
    ).fetchone()
    if not so:
        return RedirectResponse("/sales-orders", status_code=303)

    lines = [dict(r) for r in conn.execute(
        """SELECT sl.*, i.item_code, i.item_name, i.unit
           FROM so_lines sl JOIN items i ON sl.item_id=i.id
           WHERE sl.so_id=? ORDER BY sl.line_no""", (so_id,)
    ).fetchall()]

    return templates.TemplateResponse(request=request, name="erp/trade_statement.html", context={
        "request": request, "doc_type": "sales",
        "doc_number": so["so_number"], "doc_date": so["order_date"],
        "supplier": COMPANY_INFO,
        "buyer": {
            "name": so["customer_name"] or "", "biz_no": so["customer_biz_no"] or "",
            "representative": so["customer_rep"] or "", "address": so["customer_addr"] or "",
        },
        "lines": lines,
        "total_amount": so["total_amount"], "tax_amount": so["tax_amount"],
    })
