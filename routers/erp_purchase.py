from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.deps import get_db, require_login, templates
from core.tz import now_kst, today_kst

router = APIRouter()

PO_STATUS = {
    "draft": "임시저장",
    "confirmed": "확정",
    "partial": "부분입고",
    "completed": "입고완료",
    "cancelled": "취소",
}

PO_STATUS_CLASS = {
    "draft": "status-badge status-wait",
    "confirmed": "status-badge status-progress",
    "partial": "status-badge status-progress",
    "completed": "status-badge status-done",
    "cancelled": "status-badge status-reject",
}

GR_STATUS = {
    "draft": "임시저장",
    "confirmed": "확정",
}


def _next_po_number(conn):
    year = today_kst().year
    row = conn.execute(
        "SELECT po_number FROM purchase_orders WHERE po_number LIKE ? ORDER BY id DESC LIMIT 1",
        (f"PO-{year}-%",),
    ).fetchone()
    if row:
        seq = int(row["po_number"].split("-")[-1]) + 1
    else:
        seq = 1
    return f"PO-{year}-{seq:04d}"


def _next_gr_number(conn):
    year = today_kst().year
    row = conn.execute(
        "SELECT gr_number FROM goods_receipts WHERE gr_number LIKE ? ORDER BY id DESC LIMIT 1",
        (f"GR-{year}-%",),
    ).fetchone()
    if row:
        seq = int(row["gr_number"].split("-")[-1]) + 1
    else:
        seq = 1
    return f"GR-{year}-{seq:04d}"


@router.get("/api/items/search")
async def api_items_search(request: Request, q: str = "",
                           u: dict = Depends(require_login), conn=Depends(get_db)):
    sql = "SELECT id, item_code, item_name, unit, unit_price FROM items WHERE is_active=1"
    params = []
    if q:
        sql += " AND (item_code LIKE ? OR item_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY item_code LIMIT 20"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    return rows


@router.get("/purchase-orders", response_class=HTMLResponse)
async def po_list(request: Request, status: str = "", partner: str = "",
                  u: dict = Depends(require_login), conn=Depends(get_db)):
    sql = """
        SELECT po.*, p.name as partner_name
        FROM purchase_orders po
        LEFT JOIN partners p ON po.partner_id=p.id
        WHERE 1=1
    """
    params = []
    if status:
        sql += " AND po.status=?"
        params.append(status)
    if partner:
        sql += " AND (p.name LIKE ? OR p.code LIKE ?)"
        params += [f"%{partner}%", f"%{partner}%"]
    sql += " ORDER BY po.id DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["status_label"] = PO_STATUS.get(r["status"], r["status"])
        r["status_class"] = PO_STATUS_CLASS.get(r["status"], "")
    return templates.TemplateResponse(request=request, name="erp/po_list.html", context={
        "request": request, "page_title": "발주 목록",
        "user_name": u["user_name"],
        "orders": rows, "status": status, "partner": partner,
        "po_status": PO_STATUS,
    })


@router.get("/purchase-orders/new", response_class=HTMLResponse)
async def po_form_new(request: Request,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    partners = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM partners WHERE is_active=1 AND partner_type IN ('supplier','both') ORDER BY code"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/po_form.html", context={
        "request": request, "page_title": "발주서 작성",
        "user_name": u["user_name"],
        "po": None, "partners": partners,
        "today": today_kst().isoformat(),
    })


@router.get("/purchase-orders/{po_id}/edit", response_class=HTMLResponse)
async def po_form_edit(request: Request, po_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    po = conn.execute("SELECT * FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
    if not po or po["status"] != "draft":
        return RedirectResponse("/purchase-orders", status_code=303)
    po = dict(po)
    po["lines"] = [dict(r) for r in conn.execute(
        """SELECT pl.*, i.item_code, i.item_name, i.unit
           FROM po_lines pl JOIN items i ON pl.item_id=i.id
           WHERE pl.po_id=? ORDER BY pl.line_no""", (po_id,)
    ).fetchall()]
    partners = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM partners WHERE is_active=1 AND partner_type IN ('supplier','both') ORDER BY code"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/po_form.html", context={
        "request": request, "page_title": "발주서 수정",
        "user_name": u["user_name"],
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

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    total = 0
    for ln in line_nums:
        item_id = int(form.get(f"item_id_{ln}", 0) or 0)
        qty = int(form.get(f"qty_{ln}", 0) or 0)
        price = int(form.get(f"price_{ln}", 0) or 0)
        if item_id and qty > 0:
            amt = qty * price
            lines.append((item_id, qty, price, amt))
            total += amt

    if not lines:
        return RedirectResponse("/purchase-orders/new", status_code=303)

    tax = int(total * 0.1)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

    if po_id:
        conn.execute(
            """UPDATE purchase_orders SET partner_id=?, po_date=?, delivery_date=?,
               total_amount=?, tax_amount=?, notes=?, updated_at=? WHERE id=? AND status='draft'""",
            (partner_id or None, po_date, delivery_date, total, tax, notes, now, po_id),
        )
        conn.execute("DELETE FROM po_lines WHERE po_id=?", (po_id,))
    else:
        po_number = _next_po_number(conn)
        cur = conn.execute(
            """INSERT INTO purchase_orders (po_number, partner_id, po_date, delivery_date,
               total_amount, tax_amount, notes, created_by)
               VALUES (?,?,?,?,?,?,?,?)""",
            (po_number, partner_id or None, po_date, delivery_date, total, tax, notes, u["user_id"]),
        )
        po_id = cur.lastrowid

    for i, (item_id, qty, price, amt) in enumerate(lines, 1):
        conn.execute(
            "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,?,?,?,?,?)",
            (po_id, i, item_id, qty, price, amt),
        )

    conn.commit()
    return RedirectResponse(f"/purchase-orders/{po_id}", status_code=303)


@router.get("/purchase-orders/{po_id}", response_class=HTMLResponse)
async def po_detail(request: Request, po_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    po = conn.execute(
        """SELECT po.*, p.name as partner_name, p.code as partner_code,
                  p.biz_no as partner_biz_no, p.phone as partner_phone,
                  p.contact_name as partner_contact, p.contact_phone as partner_contact_phone,
                  u.name as creator_name
           FROM purchase_orders po
           LEFT JOIN partners p ON po.partner_id=p.id
           LEFT JOIN users u ON po.created_by=u.id
           WHERE po.id=?""", (po_id,)
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
        """SELECT gr.*, w.name as warehouse_name
           FROM goods_receipts gr
           LEFT JOIN warehouses w ON gr.warehouse_id=w.id
           WHERE gr.po_id=? ORDER BY gr.id DESC""", (po_id,)
    ).fetchall()]
    for g in grs:
        g["status_label"] = GR_STATUS.get(g["status"], g["status"])

    return templates.TemplateResponse(request=request, name="erp/po_detail.html", context={
        "request": request, "page_title": f"발주서 {po['po_number']}",
        "user_name": u["user_name"],
        "po": po, "lines": lines, "grs": grs,
    })


@router.post("/purchase-orders/{po_id}/confirm")
async def po_confirm(request: Request, po_id: int,
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    po = conn.execute("SELECT status FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
    if not po or po["status"] != "draft":
        return JSONResponse({"error": "확정할 수 없는 상태입니다."}, status_code=400)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE purchase_orders SET status='confirmed', updated_at=? WHERE id=?",
        (now, po_id),
    )
    conn.commit()
    return RedirectResponse(f"/purchase-orders/{po_id}", status_code=303)


@router.post("/purchase-orders/{po_id}/cancel")
async def po_cancel(request: Request, po_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    po = conn.execute("SELECT status FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
    if not po or po["status"] not in ("draft", "confirmed"):
        return JSONResponse({"error": "취소할 수 없는 상태입니다."}, status_code=400)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE purchase_orders SET status='cancelled', updated_at=? WHERE id=?",
        (now, po_id),
    )
    conn.commit()
    return RedirectResponse(f"/purchase-orders/{po_id}", status_code=303)


@router.get("/goods-receipts/new", response_class=HTMLResponse)
async def gr_form_new(request: Request, po_id: int = 0,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    po = None
    po_lines = []
    if po_id:
        po = conn.execute(
            """SELECT po.*, p.name as partner_name
               FROM purchase_orders po
               LEFT JOIN partners p ON po.partner_id=p.id
               WHERE po.id=? AND po.status IN ('confirmed','partial')""", (po_id,)
        ).fetchone()
        if po:
            po = dict(po)
            po_lines = [dict(r) for r in conn.execute(
                """SELECT pl.*, i.item_code, i.item_name, i.unit,
                          (pl.quantity - pl.received_qty) as remaining_qty
                   FROM po_lines pl JOIN items i ON pl.item_id=i.id
                   WHERE pl.po_id=? AND pl.quantity > pl.received_qty
                   ORDER BY pl.line_no""", (po_id,)
            ).fetchall()]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE is_active=1 ORDER BY code"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/gr_form.html", context={
        "request": request, "page_title": "입고 등록",
        "user_name": u["user_name"],
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

    if not warehouse_id:
        return RedirectResponse(f"/goods-receipts/new?po_id={po_id}", status_code=303)

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    for ln in line_nums:
        po_line_id = int(form.get(f"po_line_id_{ln}", 0) or 0)
        item_id = int(form.get(f"item_id_{ln}", 0) or 0)
        recv_qty = int(form.get(f"recv_qty_{ln}", 0) or 0)
        defect_qty = int(form.get(f"defect_qty_{ln}", 0) or 0)
        if item_id and recv_qty > 0:
            lines.append((po_line_id, item_id, recv_qty, defect_qty))

    if not lines:
        return RedirectResponse(f"/goods-receipts/new?po_id={po_id}", status_code=303)

    uid = u["user_id"]
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    gr_number = _next_gr_number(conn)

    cur = conn.execute(
        """INSERT INTO goods_receipts (gr_number, po_id, warehouse_id, receipt_date, status, notes, created_by)
           VALUES (?,?,?,?,?,?,?)""",
        (gr_number, po_id or None, warehouse_id, receipt_date, "confirmed", notes, uid),
    )
    gr_id = cur.lastrowid

    total_amount = 0
    for i, (po_line_id, item_id, recv_qty, defect_qty) in enumerate(lines, 1):
        conn.execute(
            "INSERT INTO gr_lines (gr_id, po_line_id, item_id, received_qty, defective_qty) VALUES (?,?,?,?,?)",
            (gr_id, po_line_id or None, item_id, recv_qty, defect_qty),
        )

        good_qty = recv_qty - defect_qty

        existing = conn.execute(
            "SELECT id, quantity FROM stock WHERE item_id=? AND warehouse_id=?",
            (item_id, warehouse_id),
        ).fetchone()
        if existing:
            new_qty = existing["quantity"] + good_qty
            conn.execute("UPDATE stock SET quantity=? WHERE id=?", (new_qty, existing["id"]))
        else:
            new_qty = good_qty
            conn.execute(
                "INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,?)",
                (item_id, warehouse_id, good_qty),
            )

        conn.execute(
            """INSERT INTO stock_transactions (item_id, warehouse_id, trans_date, trans_type,
               quantity, ref_type, ref_id, balance_qty, created_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (item_id, warehouse_id, receipt_date, "in", good_qty, "gr", gr_id, new_qty, uid),
        )

        if po_line_id:
            conn.execute(
                "UPDATE po_lines SET received_qty = received_qty + ? WHERE id=?",
                (recv_qty, po_line_id),
            )
            pl = conn.execute("SELECT unit_price FROM po_lines WHERE id=?", (po_line_id,)).fetchone()
            if pl:
                total_amount += good_qty * pl["unit_price"]

    if po_id:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM po_lines WHERE po_id=? AND quantity > received_qty",
            (po_id,),
        ).fetchone()[0]
        if remaining == 0:
            conn.execute("UPDATE purchase_orders SET status='completed', updated_at=? WHERE id=?", (now, po_id))
        else:
            po_row = conn.execute("SELECT status FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
            if po_row and po_row["status"] == "confirmed":
                conn.execute("UPDATE purchase_orders SET status='partial', updated_at=? WHERE id=?", (now, po_id))

    if total_amount > 0:
        _create_gr_slip(conn, gr_id, gr_number, total_amount, uid, receipt_date, now)

    conn.commit()
    return RedirectResponse(f"/goods-receipts/{gr_id}", status_code=303)


def _create_gr_slip(conn, gr_id, gr_number, amount, uid, receipt_date, now):
    title = f"입고 전표 ({gr_number})"
    cur = conn.execute(
        """INSERT INTO erp_docs (user_id, doc_type, title, content, status, slip_type, slip_date, slip_total)
           VALUES (?,?,?,?,?,?,?,?)""",
        (uid, "expense", title, f"입고번호 {gr_number} 자동 생성 전표", "done", "대체", receipt_date, amount),
    )
    doc_id = cur.lastrowid
    year = today_kst().year
    doc_number = f"EXP-{year}-{doc_id:04d}"
    conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, doc_id))

    conn.execute(
        "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
        (doc_id, 1, "[120] 상품", "120", amount, 0, "", f"입고 {gr_number}"),
    )
    conn.execute(
        "INSERT INTO slip_lines (doc_id, line_no, account_name, account_code, debit, credit, partner, summary) VALUES (?,?,?,?,?,?,?,?)",
        (doc_id, 2, "[201] 외상매입금", "201", 0, amount, "", f"입고 {gr_number}"),
    )


@router.get("/goods-receipts/{gr_id}", response_class=HTMLResponse)
async def gr_detail(request: Request, gr_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    gr = conn.execute(
        """SELECT gr.*, w.name as warehouse_name, u.name as creator_name,
                  po.po_number, p.name as partner_name
           FROM goods_receipts gr
           LEFT JOIN warehouses w ON gr.warehouse_id=w.id
           LEFT JOIN users u ON gr.created_by=u.id
           LEFT JOIN purchase_orders po ON gr.po_id=po.id
           LEFT JOIN partners p ON po.partner_id=p.id
           WHERE gr.id=?""", (gr_id,)
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

    return templates.TemplateResponse(request=request, name="erp/gr_detail.html", context={
        "request": request, "page_title": f"입고 {gr['gr_number']}",
        "user_name": u["user_name"],
        "gr": gr, "lines": lines,
    })
