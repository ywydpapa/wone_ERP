import sqlite3
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.deps import get_db, require_login, templates
from core.task_link import stamp_task, erp_scope, task_locked
from core.erp_log import log_activity
from core.tz import now_kst, today_kst

router = APIRouter()

WO_STATUS = {
    "planned": "계획",
    "released": "착수",
    "in_progress": "진행중",
    "completed": "완료",
    "cancelled": "취소",
}

WO_STATUS_CLASS = {
    "planned": "status-badge status-wait",
    "released": "status-badge status-progress",
    "in_progress": "status-badge status-progress",
    "completed": "status-badge status-done",
    "cancelled": "status-badge status-reject",
}


def _next_wo_number(conn, seq_hint=None):
    year = today_kst().year
    if seq_hint is None:
        row = conn.execute(
            "SELECT wo_number FROM work_orders WHERE wo_number LIKE ? ORDER BY id DESC LIMIT 1",
            (f"WO-{year}-%",),
        ).fetchone()
        seq_hint = int(row["wo_number"].split("-")[-1]) + 1 if row else 1
    return f"WO-{year}-{seq_hint:04d}", seq_hint


# ── BOM ──

@router.get("/bom", response_class=HTMLResponse)
async def bom_list(request: Request, product: str = "",
                   u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "bh")
    sql = f"""
        SELECT bh.*, i.item_code, i.item_name,
               (SELECT COUNT(*) FROM bom_lines bl WHERE bl.bom_id=bh.id) as line_count
        FROM bom_headers bh
        JOIN items i ON bh.product_id=i.id
        WHERE {scope_sql}
    """
    params = [*scope_args]
    if product:
        sql += " AND (i.item_code LIKE ? OR i.item_name LIKE ?)"
        params += [f"%{product}%", f"%{product}%"]
    sql += " ORDER BY bh.id DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/bom_list.html", context={
        "request": request, "page_title": "자재명세(BOM) 목록",
        "user_name": u["name"],
        "boms": rows, "product": product,
    })


@router.get("/bom/new", response_class=HTMLResponse)
async def bom_form_new(request: Request,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    products = [dict(r) for r in conn.execute(
        "SELECT id, item_code, item_name FROM items WHERE is_active=1 AND item_type IN ('product','semi') ORDER BY item_code"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/bom_form.html", context={
        "request": request, "page_title": "자재명세 등록",
        "user_name": u["name"],
        "bom": None, "products": products,
        "today": today_kst().isoformat(),
    })


@router.get("/bom/{bom_id}/edit", response_class=HTMLResponse)
async def bom_form_edit(request: Request, bom_id: int,
                        u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "bh")
    bom = conn.execute(
        f"SELECT bh.* FROM bom_headers bh WHERE bh.id=? AND {scope_sql}",
        (bom_id, *scope_args),
    ).fetchone()
    if not bom:
        return RedirectResponse("/bom", status_code=303)
    bom = dict(bom)
    bom["lines"] = [dict(r) for r in conn.execute(
        """SELECT bl.*, i.item_code, i.item_name, i.unit
           FROM bom_lines bl JOIN items i ON bl.component_id=i.id
           WHERE bl.bom_id=? ORDER BY bl.id""", (bom_id,)
    ).fetchall()]
    products = [dict(r) for r in conn.execute(
        "SELECT id, item_code, item_name FROM items WHERE is_active=1 AND item_type IN ('product','semi') ORDER BY item_code"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/bom_form.html", context={
        "request": request, "page_title": "자재명세 수정",
        "user_name": u["name"],
        "bom": bom, "products": products,
        "today": today_kst().isoformat(),
    })


@router.post("/bom/save")
async def bom_save(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    bom_id = int(form.get("bom_id", 0) or 0)
    product_id = int(form.get("product_id", 0) or 0)
    bom_version = form.get("bom_version", "1.0")
    effective_date = form.get("effective_date", "")

    if not product_id:
        return RedirectResponse("/bom/new", status_code=303)

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    for ln in line_nums:
        comp_id = int(form.get(f"component_id_{ln}", 0) or 0)
        qty = float(form.get(f"qty_{ln}", 0) or 0)
        unit = form.get(f"unit_{ln}", "EA")
        step = form.get(f"step_{ln}", "")
        if comp_id and qty > 0:
            lines.append((comp_id, qty, unit, step))

    if not lines:
        return RedirectResponse("/bom/new", status_code=303)

    is_new = not bool(bom_id)

    if bom_id:
        existing = conn.execute("SELECT task_id FROM bom_headers WHERE id=?", (bom_id,)).fetchone()
        if existing and task_locked(conn, existing["task_id"]):
            return RedirectResponse(f"/bom/{bom_id}?error=locked", status_code=303)
        conn.execute(
            "UPDATE bom_headers SET product_id=?, bom_version=?, effective_date=? WHERE id=?",
            (product_id, bom_version, effective_date or None, bom_id),
        )
        conn.execute("DELETE FROM bom_lines WHERE bom_id=?", (bom_id,))
    else:
        task_id = stamp_task(conn, request, u["id"], "production")
        cur = conn.execute(
            "INSERT INTO bom_headers (product_id, bom_version, effective_date, created_by, task_id) VALUES (?,?,?,?,?)",
            (product_id, bom_version, effective_date or None, u["id"], task_id),
        )
        bom_id = cur.lastrowid

    for comp_id, qty, unit, step in lines:
        conn.execute(
            "INSERT INTO bom_lines (bom_id, component_id, quantity, unit, process_step) VALUES (?,?,?,?,?)",
            (bom_id, comp_id, qty, unit, step or None),
        )

    irow = conn.execute("SELECT item_name FROM items WHERE id=?", (product_id,)).fetchone()
    iname = irow["item_name"] if irow else ""
    if is_new:
        log_activity(conn, u["id"], "create", "production", bom_id, "", f"BOM 등록 ({iname})")
    else:
        log_activity(conn, u["id"], "update", "production", bom_id, "", f"BOM 수정 ({iname})")

    conn.commit()
    return RedirectResponse(f"/bom/{bom_id}", status_code=303)


@router.get("/bom/{bom_id}", response_class=HTMLResponse)
async def bom_detail(request: Request, bom_id: int,
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "bh")
    bom = conn.execute(
        f"""SELECT bh.*, i.item_code, i.item_name
           FROM bom_headers bh JOIN items i ON bh.product_id=i.id
           WHERE bh.id=? AND {scope_sql}""", (bom_id, *scope_args)
    ).fetchone()
    if not bom:
        return RedirectResponse("/bom", status_code=303)
    bom = dict(bom)
    bom['created_date'] = bom['created_at'][:10] if bom.get('created_at') else '-'

    lines = [dict(r) for r in conn.execute(
        """SELECT bl.*, i.item_code, i.item_name, i.unit as item_unit
           FROM bom_lines bl JOIN items i ON bl.component_id=i.id
           WHERE bl.bom_id=? ORDER BY bl.id""", (bom_id,)
    ).fetchall()]

    return templates.TemplateResponse(request=request, name="erp/bom_detail.html", context={
        "request": request, "page_title": f"자재명세 {bom['item_name']} v{bom['bom_version']}",
        "user_name": u["name"],
        "bom": bom, "lines": lines,
    })


@router.post("/bom/{bom_id}/delete")
async def bom_delete(request: Request, bom_id: int,
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    bom_row = conn.execute("SELECT task_id FROM bom_headers WHERE id=?", (bom_id,)).fetchone()
    if bom_row and task_locked(conn, bom_row["task_id"]):
        return JSONResponse({"error": "승인된 태스크의 BOM은 삭제할 수 없습니다"}, status_code=403)
    used = conn.execute(
        "SELECT COUNT(*) FROM work_orders WHERE bom_id=? AND status NOT IN ('cancelled')",
        (bom_id,),
    ).fetchone()[0]
    if used:
        return JSONResponse({"error": "사용 중인 작업지시가 있어 삭제할 수 없습니다."}, status_code=400)
    conn.execute("DELETE FROM bom_lines WHERE bom_id=?", (bom_id,))
    conn.execute("DELETE FROM bom_headers WHERE id=?", (bom_id,))
    log_activity(conn, u["id"], "delete", "production", bom_id, "", f"BOM 삭제 (ID: {bom_id})")
    conn.commit()
    return RedirectResponse("/bom", status_code=303)


# ── 작업지시 ──

@router.get("/work-orders", response_class=HTMLResponse)
async def wo_list(request: Request, status: str = "", product: str = "",
                  u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "wo")
    sql = f"""
        SELECT wo.*, i.item_code, i.item_name
        FROM work_orders wo
        JOIN items i ON wo.product_id=i.id
        WHERE {scope_sql}
    """
    params = [*scope_args]
    if status:
        sql += " AND wo.status=?"
        params.append(status)
    if product:
        sql += " AND (i.item_code LIKE ? OR i.item_name LIKE ?)"
        params += [f"%{product}%", f"%{product}%"]
    sql += " ORDER BY wo.id DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["status_label"] = WO_STATUS.get(r["status"], r["status"])
        r["status_class"] = WO_STATUS_CLASS.get(r["status"], "")
    return templates.TemplateResponse(request=request, name="erp/wo_list.html", context={
        "request": request, "page_title": "작업지시 목록",
        "user_name": u["name"],
        "orders": rows, "status": status, "product": product,
        "wo_status": WO_STATUS,
    })


@router.get("/work-orders/new", response_class=HTMLResponse)
async def wo_form_new(request: Request,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    boms = [dict(r) for r in conn.execute(
        """SELECT bh.id, bh.bom_version, i.item_code, i.item_name, bh.product_id
           FROM bom_headers bh JOIN items i ON bh.product_id=i.id
           WHERE bh.is_active=1 ORDER BY i.item_code"""
    ).fetchall()]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE is_active=1 ORDER BY code"
    ).fetchall()]
    workers = [dict(r) for r in conn.execute(
        "SELECT e.id, e.name FROM employees e WHERE e.status='active' ORDER BY e.name"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/wo_form.html", context={
        "request": request, "page_title": "작업지시 등록",
        "user_name": u["name"],
        "wo": None, "boms": boms, "warehouses": warehouses, "workers": workers,
        "today": today_kst().isoformat(),
    })


@router.get("/work-orders/{wo_id}/edit", response_class=HTMLResponse)
async def wo_form_edit(request: Request, wo_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "wo")
    wo = conn.execute(
        f"SELECT wo.* FROM work_orders wo WHERE wo.id=? AND {scope_sql}",
        (wo_id, *scope_args),
    ).fetchone()
    if not wo or wo["status"] != "planned":
        return RedirectResponse("/work-orders", status_code=303)
    wo = dict(wo)
    wo['start_date'] = wo['planned_start'][:10] if wo.get('planned_start') else ''
    wo['end_date'] = wo['planned_end'][:10] if wo.get('planned_end') else ''
    boms = [dict(r) for r in conn.execute(
        """SELECT bh.id, bh.bom_version, i.item_code, i.item_name, bh.product_id
           FROM bom_headers bh JOIN items i ON bh.product_id=i.id
           WHERE bh.is_active=1 ORDER BY i.item_code"""
    ).fetchall()]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE is_active=1 ORDER BY code"
    ).fetchall()]
    workers = [dict(r) for r in conn.execute(
        "SELECT e.id, e.name FROM employees e WHERE e.status='active' ORDER BY e.name"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/wo_form.html", context={
        "request": request, "page_title": "작업지시 수정",
        "user_name": u["name"],
        "wo": wo, "boms": boms, "warehouses": warehouses, "workers": workers,
        "today": today_kst().isoformat(),
    })


@router.post("/work-orders/save")
async def wo_save(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    wo_id = int(form.get("wo_id", 0) or 0)
    bom_id = int(form.get("bom_id", 0) or 0)
    planned_qty = int(form.get("planned_qty", 0) or 0)
    planned_start = form.get("planned_start", "")
    planned_end = form.get("planned_end", "")
    worker_id = int(form.get("worker_id", 0) or 0)
    notes = form.get("notes", "")

    if not bom_id or planned_qty <= 0:
        return RedirectResponse("/work-orders/new", status_code=303)

    bom = conn.execute("SELECT product_id FROM bom_headers WHERE id=?", (bom_id,)).fetchone()
    if not bom:
        return RedirectResponse("/work-orders/new", status_code=303)
    product_id = bom["product_id"]
    is_new = not bool(wo_id)

    if wo_id:
        existing = conn.execute("SELECT task_id FROM work_orders WHERE id=?", (wo_id,)).fetchone()
        if existing and task_locked(conn, existing["task_id"]):
            return RedirectResponse(f"/work-orders/{wo_id}?error=locked", status_code=303)
        conn.execute(
            """UPDATE work_orders SET product_id=?, bom_id=?, planned_qty=?,
               planned_start=?, planned_end=?, worker_id=?, notes=?
               WHERE id=? AND status='planned'""",
            (product_id, bom_id, planned_qty, planned_start or None,
             planned_end or None, worker_id or None, notes, wo_id),
        )
    else:
        wo_number, wo_seq = _next_wo_number(conn)
        task_id = stamp_task(conn, request, u["id"], "production")
        while True:
            try:
                cur = conn.execute(
                    """INSERT INTO work_orders (wo_number, product_id, bom_id, planned_qty,
                       planned_start, planned_end, worker_id, notes, created_by, task_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (wo_number, product_id, bom_id, planned_qty,
                     planned_start or None, planned_end or None,
                     worker_id or None, notes, u["id"], task_id),
                )
                break
            except sqlite3.IntegrityError:
                wo_seq += 1
                wo_number, _ = _next_wo_number(conn, wo_seq)
        wo_id = cur.lastrowid

    if is_new:
        log_activity(conn, u["id"], "create", "production", wo_id, wo_number, f"작업지시 등록 {wo_number}")
    else:
        worow = conn.execute("SELECT wo_number FROM work_orders WHERE id=?", (wo_id,)).fetchone()
        wo_number = worow["wo_number"] if worow else ""
        log_activity(conn, u["id"], "update", "production", wo_id, wo_number, f"작업지시 수정 {wo_number}")

    conn.commit()
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)


@router.get("/work-orders/{wo_id}", response_class=HTMLResponse)
async def wo_detail(request: Request, wo_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "wo")
    wo = conn.execute(
        f"""SELECT wo.*, i.item_code, i.item_name,
                  bh.bom_version, e.name as worker_name, u.name as creator_name
           FROM work_orders wo
           JOIN items i ON wo.product_id=i.id
           LEFT JOIN bom_headers bh ON wo.bom_id=bh.id
           LEFT JOIN employees e ON wo.worker_id=e.id
           LEFT JOIN users u ON wo.created_by=u.id
           WHERE wo.id=? AND {scope_sql}""", (wo_id, *scope_args)
    ).fetchone()
    if not wo:
        return RedirectResponse("/work-orders", status_code=303)
    wo = dict(wo)
    wo["status_label"] = WO_STATUS.get(wo["status"], wo["status"])
    wo["status_class"] = WO_STATUS_CLASS.get(wo["status"], "")

    bom_lines = []
    if wo["bom_id"]:
        bom_lines = [dict(r) for r in conn.execute(
            """SELECT bl.*, i.item_code, i.item_name, i.unit as item_unit
               FROM bom_lines bl JOIN items i ON bl.component_id=i.id
               WHERE bl.bom_id=? ORDER BY bl.id""", (wo["bom_id"],)
        ).fetchall()]
        for bl in bom_lines:
            bl['required_qty'] = bl['quantity'] * wo['planned_qty']

    results = [dict(r) for r in conn.execute(
        """SELECT pr.*, e.name as worker_name
           FROM production_results pr
           LEFT JOIN employees e ON pr.worker_id=e.id
           WHERE pr.wo_id=? ORDER BY pr.result_date DESC""", (wo_id,)
    ).fetchall()]

    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE is_active=1 ORDER BY code"
    ).fetchall()]

    return templates.TemplateResponse(request=request, name="erp/wo_detail.html", context={
        "request": request, "page_title": f"작업지시 {wo['wo_number']}",
        "user_name": u["name"],
        "wo": wo, "bom_lines": bom_lines, "results": results,
        "warehouses": warehouses,
    })


@router.post("/work-orders/{wo_id}/release")
async def wo_release(request: Request, wo_id: int,
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    warehouse_id = int(form.get("warehouse_id", 0) or 0)

    wo = conn.execute("SELECT * FROM work_orders WHERE id=?", (wo_id,)).fetchone()
    if not wo or wo["status"] != "planned":
        return JSONResponse({"error": "착수할 수 없는 상태입니다."}, status_code=400)

    if not warehouse_id:
        return JSONResponse({"error": "출고 창고를 선택해 주세요."}, status_code=400)

    bom_lines = conn.execute(
        "SELECT component_id, quantity FROM bom_lines WHERE bom_id=?",
        (wo["bom_id"],),
    ).fetchall()

    shortages = []
    for bl in bom_lines:
        need_qty = int(bl["quantity"] * wo["planned_qty"])
        if need_qty <= 0:
            continue
        stk = conn.execute(
            "SELECT quantity FROM stock WHERE item_id=? AND warehouse_id=?",
            (bl["component_id"], warehouse_id),
        ).fetchone()
        avail = stk["quantity"] if stk else 0
        if avail < need_qty:
            item = conn.execute("SELECT name FROM items WHERE id=?", (bl["component_id"],)).fetchone()
            shortages.append(f"{item['name']}: 필요 {need_qty}, 재고 {avail}")
    if shortages:
        return JSONResponse({"error": "자재 부족: " + ", ".join(shortages)}, status_code=400)

    uid = u["id"]
    now = now_kst()
    trans_date = now.strftime("%Y-%m-%d")

    for bl in bom_lines:
        need_qty = int(bl["quantity"] * wo["planned_qty"])
        if need_qty <= 0:
            continue

        existing = conn.execute(
            "SELECT id, quantity FROM stock WHERE item_id=? AND warehouse_id=?",
            (bl["component_id"], warehouse_id),
        ).fetchone()

        if existing:
            new_qty = max(0, existing["quantity"] - need_qty)
            conn.execute("UPDATE stock SET quantity=? WHERE id=?", (new_qty, existing["id"]))
        else:
            new_qty = 0

        conn.execute(
            """INSERT INTO stock_transactions (item_id, warehouse_id, trans_date, trans_type,
               quantity, ref_type, ref_id, balance_qty, created_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (bl["component_id"], warehouse_id, trans_date, "out",
             need_qty, "wo_material", wo_id, new_qty, uid),
        )

    conn.execute(
        "UPDATE work_orders SET status='released', actual_start=? WHERE id=?",
        (now.strftime("%Y-%m-%d %H:%M:%S"), wo_id),
    )
    log_activity(conn, u["id"], "release", "production", wo_id, wo["wo_number"], f"작업지시 착수 {wo['wo_number']}")
    conn.commit()
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)


@router.post("/work-orders/{wo_id}/cancel")
async def wo_cancel(request: Request, wo_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    wo = conn.execute("SELECT status, wo_number, task_id FROM work_orders WHERE id=?", (wo_id,)).fetchone()
    if not wo or wo["status"] not in ("planned",):
        return JSONResponse({"error": "취소할 수 없는 상태입니다."}, status_code=400)
    if task_locked(conn, wo["task_id"]):
        return JSONResponse({"error": "승인된 태스크의 작업지시는 취소할 수 없습니다"}, status_code=403)
    conn.execute("UPDATE work_orders SET status='cancelled' WHERE id=?", (wo_id,))
    log_activity(conn, u["id"], "cancel", "production", wo_id, wo["wo_number"], f"작업지시 취소 {wo['wo_number']}")
    conn.commit()
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)


# ── 생산실적 ──

@router.get("/production-results/new", response_class=HTMLResponse)
async def pr_form_new(request: Request, wo_id: int = 0,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    wo = None
    if wo_id:
        wo = conn.execute(
            """SELECT wo.*, i.item_code, i.item_name
               FROM work_orders wo JOIN items i ON wo.product_id=i.id
               WHERE wo.id=? AND wo.status IN ('released','in_progress')""", (wo_id,)
        ).fetchone()
        if wo:
            wo = dict(wo)
            wo["remaining_qty"] = wo["planned_qty"] - wo["actual_qty"]

    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE is_active=1 ORDER BY code"
    ).fetchall()]
    workers = [dict(r) for r in conn.execute(
        "SELECT e.id, e.name FROM employees e WHERE e.status='active' ORDER BY e.name"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/production_result_form.html", context={
        "request": request, "page_title": "생산실적 보고",
        "user_name": u["name"],
        "wo": wo, "warehouses": warehouses, "workers": workers,
        "today": today_kst().isoformat(),
    })


@router.post("/production-results/save")
async def pr_save(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    wo_id = int(form.get("wo_id", 0) or 0)
    good_qty = int(form.get("good_qty", 0) or 0)
    defect_qty = int(form.get("defect_qty", 0) or 0)
    result_date = form.get("result_date", today_kst().isoformat())
    worker_id = int(form.get("worker_id", 0) or 0)
    warehouse_id = int(form.get("warehouse_id", 0) or 0)
    notes = form.get("notes", "")

    if not wo_id or good_qty <= 0:
        return RedirectResponse(f"/production-results/new?wo_id={wo_id}", status_code=303)

    wo = conn.execute("SELECT * FROM work_orders WHERE id=?", (wo_id,)).fetchone()
    if not wo or wo["status"] not in ("released", "in_progress"):
        return RedirectResponse("/work-orders", status_code=303)

    if not warehouse_id:
        return RedirectResponse(f"/production-results/new?wo_id={wo_id}", status_code=303)

    uid = u["id"]
    task_id = stamp_task(conn, request, uid, "production")

    pr_cur = conn.execute(
        "INSERT INTO production_results (wo_id, result_date, good_qty, defect_qty, worker_id, notes, created_by, task_id) VALUES (?,?,?,?,?,?,?,?)",
        (wo_id, result_date, good_qty, defect_qty, worker_id or None, notes, uid, task_id),
    )
    result_id = pr_cur.lastrowid

    product_id = wo["product_id"]
    existing = conn.execute(
        "SELECT id, quantity FROM stock WHERE item_id=? AND warehouse_id=?",
        (product_id, warehouse_id),
    ).fetchone()
    if existing:
        new_qty = existing["quantity"] + good_qty
        conn.execute("UPDATE stock SET quantity=? WHERE id=?", (new_qty, existing["id"]))
    else:
        new_qty = good_qty
        conn.execute(
            "INSERT INTO stock (item_id, warehouse_id, quantity) VALUES (?,?,?)",
            (product_id, warehouse_id, good_qty),
        )

    conn.execute(
        """INSERT INTO stock_transactions (item_id, warehouse_id, trans_date, trans_type,
           quantity, ref_type, ref_id, balance_qty, created_by)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (product_id, warehouse_id, result_date, "in", good_qty, "wo_product", wo_id, new_qty, uid),
    )

    new_actual = wo["actual_qty"] + good_qty
    if new_actual >= wo["planned_qty"]:
        now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE work_orders SET actual_qty=?, status='completed', actual_end=? WHERE id=?",
            (new_actual, now, wo_id),
        )
    else:
        conn.execute(
            "UPDATE work_orders SET actual_qty=?, status='in_progress' WHERE id=?",
            (new_actual, wo_id),
        )

    log_activity(conn, u["id"], "create", "production", result_id, wo["wo_number"], f"생산실적 보고 {wo['wo_number']} ({good_qty}개)")
    conn.commit()
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)


@router.get("/api/bom/{bom_id}/lines")
async def api_bom_lines(request: Request, bom_id: int,
                        u: dict = Depends(require_login), conn=Depends(get_db)):
    rows = [dict(r) for r in conn.execute(
        """SELECT bl.*, i.item_code, i.item_name, i.unit
           FROM bom_lines bl JOIN items i ON bl.component_id=i.id
           WHERE bl.bom_id=? ORDER BY bl.id""", (bom_id,)
    ).fetchall()]
    return rows
