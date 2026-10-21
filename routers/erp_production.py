import sqlite3
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.deps import get_db, require_login, templates
from core import audit, stock
from core.books import book_of
from core.export import csv_response
from core.task_link import stamp_task, erp_scope, task_locked
from core.erp_log import log_activity
from core.tz import now_kst, today_kst

router = APIRouter()

BOM_SORTS = {"code": "i.item_code", "name": "i.item_name", "version": "bh.bom_version",
             "date": "bh.effective_date", "lines": "line_count", "active": "bh.is_active"}

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
async def bom_list(request: Request, product: str = "", sort: str = "", dir: str = "", export: str = "",
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
    order = BOM_SORTS.get(sort)
    sql += f" ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, bh.id DESC" if order else " ORDER BY bh.id DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    if export == "csv":
        csv_rows = [[r["item_code"], r["item_name"], r["bom_version"], r["effective_date"] or "",
                     r["line_count"], "활성" if r["is_active"] else "비활성"] for r in rows]
        return csv_response(["제품코드", "제품명", "버전", "적용일", "자재수", "상태"], csv_rows, "bom_list.csv")

    return templates.TemplateResponse(request=request, name="erp/bom_list.html", context={
        "request": request, "page_title": "자재명세(BOM) 목록",
        "user_name": u["name"],
        "boms": rows, "product": product, "sort": sort, "dir": dir,
    })


@router.get("/bom/new", response_class=HTMLResponse)
async def bom_form_new(request: Request,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    products = [dict(r) for r in conn.execute(
        """SELECT id, item_code, item_name FROM items WHERE company_id=? AND is_active=1
           AND item_type IN ('product','semi') ORDER BY item_code""", (book_of(conn, u),)
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
        """SELECT id, item_code, item_name FROM items WHERE company_id=? AND is_active=1
           AND item_type IN ('product','semi') ORDER BY item_code""", (book_of(conn, u),)
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

    book = book_of(conn, u)
    if not product_id or not conn.execute(
        "SELECT 1 FROM items WHERE id=? AND company_id=?", (product_id, book)
    ).fetchone():
        return JSONResponse({"error": "제품을 선택해 주세요."}, status_code=400)

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    for ln in line_nums:
        comp_id = int(form.get(f"component_id_{ln}", 0) or 0)
        qty = float(form.get(f"qty_{ln}", 0) or 0)
        unit = form.get(f"unit_{ln}", "EA")
        step = form.get(f"step_{ln}", "")
        if comp_id and qty > 0 and conn.execute(
            "SELECT 1 FROM items WHERE id=? AND company_id=?", (comp_id, book)
        ).fetchone():
            lines.append((comp_id, qty, unit, step))

    if not lines:
        return JSONResponse({"error": "자재를 1건 이상 입력해 주세요."}, status_code=400)

    is_new = not bool(bom_id)

    if bom_id:
        scope_sql, scope_args = erp_scope(conn, u, "bh")
        existing = conn.execute(
            f"SELECT task_id FROM bom_headers bh WHERE bh.id=? AND {scope_sql}", (bom_id, *scope_args)
        ).fetchone()
        if not existing:
            return JSONResponse({"error": "자재명세를 찾을 수 없습니다."}, status_code=404)
        if task_locked(conn, existing["task_id"]):
            return JSONResponse({"error": "승인된 태스크의 BOM은 수정할 수 없습니다."}, status_code=403)
        conn.execute(
            "UPDATE bom_headers SET product_id=?, bom_version=?, effective_date=? WHERE id=?",
            (product_id, bom_version, effective_date or None, bom_id),
        )
        conn.execute("DELETE FROM bom_lines WHERE bom_id=?", (bom_id,))
    else:
        task_id = stamp_task(conn, request, u["id"], "production")
        cur = conn.execute(
            "INSERT INTO bom_headers (product_id, bom_version, effective_date, created_by, task_id, company_id) VALUES (?,?,?,?,?,?)",
            (product_id, bom_version, effective_date or None, u["id"], task_id, book),
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
    scope_sql, scope_args = erp_scope(conn, u, "bh")
    bom_row = conn.execute(
        f"SELECT task_id FROM bom_headers bh WHERE bh.id=? AND {scope_sql}", (bom_id, *scope_args)
    ).fetchone()
    if not bom_row:
        return RedirectResponse("/bom", status_code=303)
    if task_locked(conn, bom_row["task_id"]):
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

WO_SORTS = {"no": "wo.wo_number", "name": "i.item_name", "plan_qty": "wo.planned_qty",
            "actual_qty": "wo.actual_qty", "start": "wo.planned_start", "end": "wo.planned_end",
            "status": "wo.status"}


@router.get("/work-orders", response_class=HTMLResponse)
async def wo_list(request: Request, status: str = "", product: str = "", sort: str = "", dir: str = "",
                  export: str = "", u: dict = Depends(require_login), conn=Depends(get_db)):
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
    order = WO_SORTS.get(sort)
    sql += f" ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, wo.id DESC" if order else " ORDER BY wo.id DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["status_label"] = WO_STATUS.get(r["status"], r["status"])
        r["status_class"] = WO_STATUS_CLASS.get(r["status"], "")

    if export == "csv":
        csv_rows = [[r["wo_number"], r["item_name"], r["planned_qty"], r["actual_qty"],
                     r["planned_start"] or "", r["planned_end"] or "", r["status_label"]] for r in rows]
        return csv_response(["지시번호", "제품명", "계획수량", "실적수량", "시작예정", "종료예정", "상태"],
                            csv_rows, "work_orders.csv")

    return templates.TemplateResponse(request=request, name="erp/wo_list.html", context={
        "request": request, "page_title": "작업지시 목록",
        "user_name": u["name"],
        "orders": rows, "status": status, "product": product,
        "wo_status": WO_STATUS, "sort": sort, "dir": dir,
    })


@router.get("/work-orders/new", response_class=HTMLResponse)
async def wo_form_new(request: Request,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    bh_sql, bh_args = erp_scope(conn, u, "bh")
    boms = [dict(r) for r in conn.execute(
        f"""SELECT bh.id, bh.bom_version, i.item_code, i.item_name, bh.product_id
           FROM bom_headers bh JOIN items i ON bh.product_id=i.id
           WHERE bh.is_active=1 AND {bh_sql} ORDER BY i.item_code""", bh_args
    ).fetchall()]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code", (book_of(conn, u),)
    ).fetchall()]
    e_sql, e_args = erp_scope(conn, u, "e")
    workers = [dict(r) for r in conn.execute(
        f"SELECT e.id, e.name FROM employees e WHERE e.status='active' AND {e_sql} ORDER BY e.name", e_args
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
    bh_sql, bh_args = erp_scope(conn, u, "bh")
    boms = [dict(r) for r in conn.execute(
        f"""SELECT bh.id, bh.bom_version, i.item_code, i.item_name, bh.product_id
           FROM bom_headers bh JOIN items i ON bh.product_id=i.id
           WHERE bh.is_active=1 AND {bh_sql} ORDER BY i.item_code""", bh_args
    ).fetchall()]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code", (book_of(conn, u),)
    ).fetchall()]
    e_sql, e_args = erp_scope(conn, u, "e")
    workers = [dict(r) for r in conn.execute(
        f"SELECT e.id, e.name FROM employees e WHERE e.status='active' AND {e_sql} ORDER BY e.name", e_args
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
        return JSONResponse({"error": "자재명세와 계획수량을 확인해 주세요."}, status_code=400)

    bh_sql, bh_args = erp_scope(conn, u, "bh")
    bom = conn.execute(
        f"SELECT product_id, company_id FROM bom_headers bh WHERE bh.id=? AND {bh_sql}", (bom_id, *bh_args)
    ).fetchone()
    if not bom:
        return JSONResponse({"error": "자재명세를 찾을 수 없습니다."}, status_code=400)
    product_id = bom["product_id"]

    if worker_id:
        e_sql, e_args = erp_scope(conn, u, "e")
        worker = conn.execute(f"SELECT 1 FROM employees e WHERE e.id=? AND {e_sql}", (worker_id, *e_args)).fetchone()
        if not worker:
            worker_id = 0

    is_new = not bool(wo_id)

    if wo_id:
        scope_sql, scope_args = erp_scope(conn, u, "wo")
        existing = conn.execute(
            f"SELECT task_id, status FROM work_orders wo WHERE wo.id=? AND {scope_sql}", (wo_id, *scope_args)
        ).fetchone()
        if not existing:
            return JSONResponse({"error": "작업지시를 찾을 수 없습니다."}, status_code=404)
        if task_locked(conn, existing["task_id"]):
            return JSONResponse({"error": "승인된 태스크의 작업지시는 수정할 수 없습니다."}, status_code=403)
        if existing["status"] != "planned":
            return JSONResponse({"error": "계획 상태의 작업지시만 수정할 수 있습니다."}, status_code=400)
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
                       planned_start, planned_end, worker_id, notes, created_by, task_id, company_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (wo_number, product_id, bom_id, planned_qty,
                     planned_start or None, planned_end or None,
                     worker_id or None, notes, u["id"], task_id, bom["company_id"]),
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


@router.get("/work-orders/report", response_class=HTMLResponse)
async def wo_report(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    today = today_kst()
    date_from = request.query_params.get("from") or today.replace(day=1).isoformat()
    date_to = request.query_params.get("to") or today.isoformat()

    scope_sql, scope_args = erp_scope(conn, u, "wo")
    items = {}
    for r in conn.execute(
        f"""SELECT i.id, i.item_code, i.item_name, SUM(wo.planned_qty) AS qty
            FROM work_orders wo JOIN items i ON wo.product_id=i.id
            WHERE {scope_sql} AND wo.planned_start BETWEEN ? AND ?
            GROUP BY i.id""", (*scope_args, date_from, date_to)
    ).fetchall():
        items[r["id"]] = {"item_code": r["item_code"], "item_name": r["item_name"],
                          "planned": r["qty"], "good": 0, "defect": 0}
    for r in conn.execute(
        f"""SELECT i.id, i.item_code, i.item_name, SUM(pr.good_qty) AS good, SUM(pr.defect_qty) AS defect
            FROM production_results pr JOIN work_orders wo ON pr.wo_id=wo.id JOIN items i ON wo.product_id=i.id
            WHERE {scope_sql} AND pr.result_date BETWEEN ? AND ?
            GROUP BY i.id""", (*scope_args, date_from, date_to)
    ).fetchall():
        row = items.setdefault(r["id"], {"item_code": r["item_code"], "item_name": r["item_name"],
                                         "planned": 0, "good": 0, "defect": 0})
        row["good"], row["defect"] = r["good"], r["defect"]

    rows = sorted(items.values(), key=lambda x: x["item_code"])
    for row in rows:
        total = row["good"] + row["defect"]
        row["yield_rate"] = round(row["good"] * 100 / total, 1) if total else None

    workers = [dict(r) for r in conn.execute(
        f"""SELECT COALESCE(e.name, '미지정') AS name, SUM(pr.good_qty) AS good, SUM(pr.defect_qty) AS defect
            FROM production_results pr JOIN work_orders wo ON pr.wo_id=wo.id
            LEFT JOIN employees e ON pr.worker_id=e.id
            WHERE {scope_sql} AND pr.result_date BETWEEN ? AND ?
            GROUP BY pr.worker_id ORDER BY name""", (*scope_args, date_from, date_to)
    ).fetchall()]
    for w in workers:
        total = w["good"] + w["defect"]
        w["yield_rate"] = round(w["good"] * 100 / total, 1) if total else None

    return templates.TemplateResponse(request=request, name="erp/wo_report.html", context={
        "request": request, "page_title": "생산 실적 보고",
        "user_name": u["name"], "rows": rows, "workers": workers,
        "date_from": date_from, "date_to": date_to,
    })


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
        "SELECT id, code, name FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code", (wo["company_id"],)
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

    scope_sql, scope_args = erp_scope(conn, u, "wo")
    wo = conn.execute(f"SELECT wo.* FROM work_orders wo WHERE wo.id=? AND {scope_sql}", (wo_id, *scope_args)).fetchone()
    if not wo or wo["status"] != "planned":
        return JSONResponse({"error": "착수할 수 없는 상태입니다."}, status_code=400)

    if not warehouse_id or not conn.execute(
        "SELECT 1 FROM warehouses WHERE id=? AND company_id=?", (warehouse_id, wo["company_id"])
    ).fetchone():
        return JSONResponse({"error": "출고 창고를 선택해 주세요."}, status_code=400)

    bom_lines = conn.execute(
        "SELECT component_id, quantity FROM bom_lines WHERE bom_id=?",
        (wo["bom_id"],),
    ).fetchall()

    needs = [(bl["component_id"], int(bl["quantity"] * wo["planned_qty"])) for bl in bom_lines]
    needs = [(item_id, qty) for item_id, qty in needs if qty > 0]
    shortages = []
    for item_id, need_qty in needs:
        stk = conn.execute(
            "SELECT quantity FROM stock WHERE item_id=? AND warehouse_id=?",
            (item_id, warehouse_id),
        ).fetchone()
        avail = stk["quantity"] if stk else 0
        if avail < need_qty:
            item = conn.execute("SELECT item_name FROM items WHERE id=?", (item_id,)).fetchone()
            shortages.append(f"{item['item_name']}: 필요 {need_qty}, 재고 {avail}")
    if shortages:
        return JSONResponse({"error": "자재 부족: " + ", ".join(shortages)}, status_code=400)

    uid = u["id"]
    now = now_kst()
    trans_date = now.strftime("%Y-%m-%d")

    for item_id, need_qty in needs:
        try:
            stock.move_out(conn, item_id, warehouse_id, need_qty, trans_date, "wo_material", wo_id, uid)
        except ValueError as e:
            conn.rollback()
            return JSONResponse({"error": str(e)}, status_code=400)

    conn.execute(
        "UPDATE work_orders SET status='released', actual_start=? WHERE id=?",
        (now.strftime("%Y-%m-%d %H:%M:%S"), wo_id),
    )
    log_activity(conn, u["id"], "release", "production", wo_id, wo["wo_number"], f"작업지시 착수 {wo['wo_number']}")
    audit.log(conn, u["id"], "wo_release", "work_order", wo_id, wo["wo_number"], company_id=wo["company_id"])
    conn.commit()
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)


@router.post("/work-orders/{wo_id}/cancel")
async def wo_cancel(request: Request, wo_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    scope_sql, scope_args = erp_scope(conn, u, "wo")
    wo = conn.execute(f"SELECT wo.* FROM work_orders wo WHERE wo.id=? AND {scope_sql}", (wo_id, *scope_args)).fetchone()
    if not wo or wo["status"] not in ("planned", "released", "in_progress"):
        return JSONResponse({"error": "취소할 수 없는 상태입니다."}, status_code=400)
    if task_locked(conn, wo["task_id"]):
        return JSONResponse({"error": "승인된 태스크의 작업지시는 취소할 수 없습니다"}, status_code=403)
    if wo["status"] != "planned" and conn.execute(
        "SELECT 1 FROM production_results WHERE wo_id=?", (wo_id,)
    ).fetchone():
        return JSONResponse({"error": "생산실적이 등록된 작업지시는 취소할 수 없습니다."}, status_code=400)

    if wo["status"] != "planned":
        # 착수 시 빠진 자재를 원 단가로 되돌림
        date = today_kst().isoformat()
        for item_id, wh_id, qty, amt in conn.execute(
            """SELECT item_id, warehouse_id, SUM(quantity), SUM(amount) FROM stock_transactions
               WHERE ref_type='wo_material' AND ref_id=? AND trans_type='out' GROUP BY item_id, warehouse_id""",
            (wo_id,),
        ).fetchall():
            stock.move_in(conn, item_id, wh_id, qty, date, "wo_material", wo_id, u["id"], amt / qty)

    conn.execute("UPDATE work_orders SET status='cancelled' WHERE id=?", (wo_id,))
    log_activity(conn, u["id"], "cancel", "production", wo_id, wo["wo_number"], f"작업지시 취소 {wo['wo_number']}")
    audit.log(conn, u["id"], "wo_cancel", "work_order", wo_id, wo["wo_number"], company_id=wo["company_id"])
    conn.commit()
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)


# ── 생산실적 ──

@router.get("/production-results/new", response_class=HTMLResponse)
async def pr_form_new(request: Request, wo_id: int = 0,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    wo = None
    if wo_id:
        scope_sql, scope_args = erp_scope(conn, u, "wo")
        wo = conn.execute(
            f"""SELECT wo.*, i.item_code, i.item_name
               FROM work_orders wo JOIN items i ON wo.product_id=i.id
               WHERE wo.id=? AND wo.status IN ('released','in_progress') AND {scope_sql}""",
            (wo_id, *scope_args)
        ).fetchone()
        if wo:
            wo = dict(wo)
            wo["remaining_qty"] = wo["planned_qty"] - wo["actual_qty"]

    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code", (book_of(conn, u),)
    ).fetchall()]
    e_sql, e_args = erp_scope(conn, u, "e")
    workers = [dict(r) for r in conn.execute(
        f"SELECT e.id, e.name FROM employees e WHERE e.status='active' AND {e_sql} ORDER BY e.name", e_args
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
        return JSONResponse({"error": "양품수량을 입력해 주세요."}, status_code=400)

    scope_sql, scope_args = erp_scope(conn, u, "wo")
    wo = conn.execute(f"SELECT wo.* FROM work_orders wo WHERE wo.id=? AND {scope_sql}", (wo_id, *scope_args)).fetchone()
    if not wo or wo["status"] not in ("released", "in_progress"):
        return JSONResponse({"error": "실적을 등록할 수 없는 작업지시입니다."}, status_code=400)

    if not warehouse_id or not conn.execute(
        "SELECT 1 FROM warehouses WHERE id=? AND company_id=?", (warehouse_id, wo["company_id"])
    ).fetchone():
        return JSONResponse({"error": "입고 창고를 선택해 주세요."}, status_code=400)

    if worker_id and not conn.execute(
        "SELECT 1 FROM employees WHERE id=? AND company_id=?", (worker_id, wo["company_id"])
    ).fetchone():
        worker_id = 0

    uid = u["id"]
    task_id = stamp_task(conn, request, uid, "production")

    pr_cur = conn.execute(
        "INSERT INTO production_results (wo_id, result_date, good_qty, defect_qty, worker_id, notes, created_by, task_id) VALUES (?,?,?,?,?,?,?,?)",
        (wo_id, result_date, good_qty, defect_qty, worker_id or None, notes, uid, task_id),
    )
    result_id = pr_cur.lastrowid

    stock.move_in(conn, wo["product_id"], warehouse_id, good_qty, result_date, "wo_product", wo_id, uid)

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
    scope_sql, scope_args = erp_scope(conn, u, "bh")
    bom = conn.execute(f"SELECT 1 FROM bom_headers bh WHERE bh.id=? AND {scope_sql}", (bom_id, *scope_args)).fetchone()
    if not bom:
        return []
    rows = [dict(r) for r in conn.execute(
        """SELECT bl.*, i.item_code, i.item_name, i.unit
           FROM bom_lines bl JOIN items i ON bl.component_id=i.id
           WHERE bl.bom_id=? ORDER BY bl.id""", (bom_id,)
    ).fetchall()]
    return rows
