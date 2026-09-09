from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from core.deps import get_db, require_login, templates
from core.tz import today_kst

router = APIRouter()

PER_PAGE = 20

ITEM_TYPES = {
    "material": "원재료",
    "product": "완제품",
    "semi": "반제품",
    "consumable": "소모품",
}


@router.get("/items", response_class=HTMLResponse)
async def item_list(request: Request, q: str = "", item_type: str = "", page: int = 1,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    where = "WHERE is_active=1"
    params = []
    if q:
        where += " AND (item_code LIKE ? OR item_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if item_type:
        where += " AND item_type=?"
        params.append(item_type)

    total = conn.execute(f"SELECT COUNT(*) FROM items {where}", params).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    sql = f"SELECT * FROM items {where} ORDER BY item_code LIMIT {PER_PAGE} OFFSET {(page-1)*PER_PAGE}"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["item_type_label"] = ITEM_TYPES.get(r["item_type"], r["item_type"])
    return templates.TemplateResponse(request=request, name="erp/item_list.html", context={
        "request": request, "page_title": "품목 관리",
        "user_name": u["name"],
        "items": rows, "q": q, "item_type": item_type,
        "item_types": ITEM_TYPES,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/items?q={q}&item_type={item_type}",
    })


@router.get("/items/new", response_class=HTMLResponse)
async def item_form_new(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="erp/item_form.html", context={
        "request": request, "page_title": "품목 등록",
        "user_name": u["name"],
        "item": None, "item_types": ITEM_TYPES,
    })


@router.get("/items/{item_id}/edit", response_class=HTMLResponse)
async def item_form_edit(request: Request, item_id: int,
                         u: dict = Depends(require_login), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return RedirectResponse("/items", status_code=303)
    return templates.TemplateResponse(request=request, name="erp/item_form.html", context={
        "request": request, "page_title": "품목 수정",
        "user_name": u["name"],
        "item": dict(row), "item_types": ITEM_TYPES,
    })


@router.post("/items/save", response_class=HTMLResponse)
async def item_save(request: Request,
                    item_id: int = Form(0),
                    item_code: str = Form(...),
                    item_name: str = Form(...),
                    item_type: str = Form("material"),
                    unit: str = Form("EA"),
                    unit_price: int = Form(0),
                    safety_stock: int = Form(0),
                    category: str = Form(""),
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    if item_id:
        conn.execute(
            """UPDATE items SET item_code=?, item_name=?, item_type=?, unit=?,
               unit_price=?, safety_stock=?, category=? WHERE id=?""",
            (item_code, item_name, item_type, unit, unit_price, safety_stock, category, item_id),
        )
    else:
        conn.execute(
            """INSERT INTO items (item_code, item_name, item_type, unit, unit_price, safety_stock, category)
               VALUES (?,?,?,?,?,?,?)""",
            (item_code, item_name, item_type, unit, unit_price, safety_stock, category),
        )
    conn.commit()
    return RedirectResponse("/items", status_code=303)


PARTNER_TYPES = {
    "supplier": "공급처",
    "customer": "고객",
    "both": "공급/고객",
}


@router.get("/partners", response_class=HTMLResponse)
async def partner_list(request: Request, q: str = "", ptype: str = "", page: int = 1,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    where = "WHERE is_active=1"
    params = []
    if q:
        where += " AND (code LIKE ? OR name LIKE ? OR biz_no LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if ptype:
        where += " AND partner_type=?"
        params.append(ptype)

    total = conn.execute(f"SELECT COUNT(*) FROM partners {where}", params).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    sql = f"SELECT * FROM partners {where} ORDER BY code LIMIT {PER_PAGE} OFFSET {(page-1)*PER_PAGE}"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["type_label"] = PARTNER_TYPES.get(r.get("partner_type", ""), "공급처")
    return templates.TemplateResponse(request=request, name="erp/partner_list.html", context={
        "request": request, "page_title": "거래처 관리",
        "user_name": u["name"],
        "partners": rows, "q": q, "ptype": ptype,
        "partner_types": PARTNER_TYPES,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/partners?q={q}&ptype={ptype}",
    })


@router.get("/partners/new", response_class=HTMLResponse)
async def partner_form_new(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="erp/partner_form.html", context={
        "request": request, "page_title": "거래처 등록",
        "user_name": u["name"],
        "partner": None, "partner_types": PARTNER_TYPES,
    })


@router.get("/partners/{partner_id}/edit", response_class=HTMLResponse)
async def partner_form_edit(request: Request, partner_id: int,
                            u: dict = Depends(require_login), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM partners WHERE id=?", (partner_id,)).fetchone()
    if not row:
        return RedirectResponse("/partners", status_code=303)
    return templates.TemplateResponse(request=request, name="erp/partner_form.html", context={
        "request": request, "page_title": "거래처 수정",
        "user_name": u["name"],
        "partner": dict(row), "partner_types": PARTNER_TYPES,
    })


@router.post("/partners/save", response_class=HTMLResponse)
async def partner_save(request: Request,
                       partner_id: int = Form(0),
                       code: str = Form(...),
                       name: str = Form(...),
                       partner_type: str = Form("supplier"),
                       biz_no: str = Form(""),
                       representative: str = Form(""),
                       biz_type: str = Form(""),
                       biz_item: str = Form(""),
                       address: str = Form(""),
                       phone: str = Form(""),
                       email: str = Form(""),
                       fax: str = Form(""),
                       contact_name: str = Form(""),
                       contact_phone: str = Form(""),
                       contact_email: str = Form(""),
                       notes: str = Form(""),
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    if partner_id:
        conn.execute(
            """UPDATE partners SET code=?, name=?, partner_type=?, biz_no=?, representative=?,
               biz_type=?, biz_item=?, address=?, phone=?, email=?, fax=?,
               contact_name=?, contact_phone=?, contact_email=?, notes=? WHERE id=?""",
            (code, name, partner_type, biz_no, representative, biz_type, biz_item,
             address, phone, email, fax, contact_name, contact_phone, contact_email, notes, partner_id),
        )
    else:
        conn.execute(
            """INSERT INTO partners (code, name, partner_type, biz_no, representative,
               biz_type, biz_item, address, phone, email, fax,
               contact_name, contact_phone, contact_email, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (code, name, partner_type, biz_no, representative, biz_type, biz_item,
             address, phone, email, fax, contact_name, contact_phone, contact_email, notes),
        )
    conn.commit()
    return RedirectResponse("/partners", status_code=303)


@router.get("/warehouses", response_class=HTMLResponse)
async def warehouse_list(request: Request,
                         u: dict = Depends(require_login), conn=Depends(get_db)):
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM warehouses WHERE is_active=1 ORDER BY code"
    ).fetchall()]
    for r in rows:
        r["item_count"] = conn.execute(
            "SELECT COUNT(DISTINCT item_id) FROM stock WHERE warehouse_id=? AND quantity>0",
            (r["id"],),
        ).fetchone()[0]
        r["total_qty"] = conn.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM stock WHERE warehouse_id=?",
            (r["id"],),
        ).fetchone()[0]
    return templates.TemplateResponse(request=request, name="erp/warehouse_list.html", context={
        "request": request, "page_title": "창고 관리",
        "user_name": u["name"],
        "warehouses": rows,
    })


@router.get("/warehouses/new", response_class=HTMLResponse)
async def warehouse_form_new(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="erp/warehouse_form.html", context={
        "request": request, "page_title": "창고 등록",
        "user_name": u["name"],
        "warehouse": None,
    })


@router.get("/warehouses/{wh_id}/edit", response_class=HTMLResponse)
async def warehouse_form_edit(request: Request, wh_id: int,
                              u: dict = Depends(require_login), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM warehouses WHERE id=?", (wh_id,)).fetchone()
    if not row:
        return RedirectResponse("/warehouses", status_code=303)
    return templates.TemplateResponse(request=request, name="erp/warehouse_form.html", context={
        "request": request, "page_title": "창고 수정",
        "user_name": u["name"],
        "warehouse": dict(row),
    })


@router.post("/warehouses/save", response_class=HTMLResponse)
async def warehouse_save(request: Request,
                         wh_id: int = Form(0),
                         code: str = Form(...),
                         name: str = Form(...),
                         location: str = Form(""),
                         u: dict = Depends(require_login), conn=Depends(get_db)):
    if wh_id:
        conn.execute(
            "UPDATE warehouses SET code=?, name=?, location=? WHERE id=?",
            (code, name, location, wh_id),
        )
    else:
        conn.execute(
            "INSERT INTO warehouses (code, name, location) VALUES (?,?,?)",
            (code, name, location),
        )
    conn.commit()
    return RedirectResponse("/warehouses", status_code=303)


@router.get("/stock", response_class=HTMLResponse)
async def stock_list(request: Request, q: str = "", wh: int = 0, low: int = 0, page: int = 1,
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    base_where = "WHERE i.is_active=1 AND w.is_active=1"
    params = []
    if q:
        base_where += " AND (i.item_code LIKE ? OR i.item_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if wh:
        base_where += " AND s.warehouse_id=?"
        params.append(wh)
    if low:
        base_where += " AND s.quantity <= i.safety_stock"

    total = conn.execute(
        f"SELECT COUNT(*) FROM stock s JOIN items i ON s.item_id=i.id JOIN warehouses w ON s.warehouse_id=w.id {base_where}",
        params,
    ).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    sql = f"""
        SELECT s.id, s.quantity, i.item_code, i.item_name, i.item_type, i.unit,
               i.safety_stock, w.code as wh_code, w.name as wh_name, i.id as item_id
        FROM stock s
        JOIN items i ON s.item_id=i.id
        JOIN warehouses w ON s.warehouse_id=w.id
        {base_where}
        ORDER BY i.item_code, w.code
        LIMIT {PER_PAGE} OFFSET {(page-1)*PER_PAGE}
    """
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["item_type_label"] = ITEM_TYPES.get(r["item_type"], r["item_type"])
        r["is_low"] = r["quantity"] <= r["safety_stock"]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE is_active=1 ORDER BY code"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/stock_list.html", context={
        "request": request, "page_title": "재고 현황",
        "user_name": u["name"],
        "stocks": rows, "q": q, "wh": wh, "low": low,
        "warehouses": warehouses, "item_types": ITEM_TYPES,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/stock?q={q}&wh={wh}&low={low}",
    })


REF_TYPE_LABELS = {
    "gr": "입고",
    "shipment": "출고",
    "wo_material": "생산출고",
    "wo_product": "생산입고",
}

TRANS_TYPE_CLASS = {
    "in": "bg-success",
    "out": "bg-danger",
    "adjust": "bg-warning text-dark",
}


@router.get("/stock/ledger", response_class=HTMLResponse)
async def stock_ledger(request: Request, item_id: int = 0, wh: int = 0,
                       date_from: str = "", date_to: str = "", page: int = 1,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE is_active=1 ORDER BY code"
    ).fetchall()]

    if not date_from:
        date_from = f"{today_kst().year}-01-01"
    if not date_to:
        date_to = today_kst().isoformat()

    base_url = f"/stock/ledger?item_id={item_id}&wh={wh}&date_from={date_from}&date_to={date_to}"

    if not item_id:
        # 품목별 요약
        where = "WHERE st.trans_date BETWEEN ? AND ?"
        params = [date_from, date_to]
        if wh:
            where += " AND st.warehouse_id=?"
            params.append(wh)

        sql = f"""
            SELECT i.id as item_id, i.item_code, i.item_name, i.unit,
                   SUM(CASE WHEN st.trans_type='in' THEN st.quantity ELSE 0 END) as total_in,
                   SUM(CASE WHEN st.trans_type='out' THEN st.quantity ELSE 0 END) as total_out
            FROM stock_transactions st
            JOIN items i ON st.item_id=i.id
            {where}
            GROUP BY i.id, i.item_code, i.item_name, i.unit
            ORDER BY i.item_code
        """
        all_rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        # 기초재고 계산
        for r in all_rows:
            bp = [date_from]
            bw = ""
            if wh:
                bw = " AND warehouse_id=?"
                bp.append(wh)
            before = conn.execute(
                f"""SELECT COALESCE(SUM(CASE WHEN trans_type='in' THEN quantity ELSE 0 END)
                    - SUM(CASE WHEN trans_type='out' THEN quantity ELSE 0 END), 0)
                    FROM stock_transactions WHERE item_id=? AND trans_date < ?{bw}""",
                [r["item_id"]] + bp,
            ).fetchone()[0]
            r["opening"] = before
            r["closing"] = before + r["total_in"] - r["total_out"]

        total = len(all_rows)
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = max(1, min(page, total_pages))
        rows = all_rows[(page - 1) * PER_PAGE:page * PER_PAGE]

        return templates.TemplateResponse(request=request, name="erp/stock_ledger.html", context={
            "request": request, "page_title": "수불부",
            "user_name": u["name"],
            "mode": "summary", "rows": rows,
            "warehouses": warehouses, "wh": wh,
            "date_from": date_from, "date_to": date_to,
            "page": page, "total_pages": total_pages, "total_count": total, "base_url": base_url,
        })

    # 품목 상세
    item = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        return RedirectResponse("/stock/ledger", status_code=303)
    item = dict(item)

    where = "WHERE st.item_id=? AND st.trans_date BETWEEN ? AND ?"
    params = [item_id, date_from, date_to]
    if wh:
        where += " AND st.warehouse_id=?"
        params.append(wh)

    total = conn.execute(f"SELECT COUNT(*) FROM stock_transactions st {where}", params).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    sql = f"""
        SELECT st.*, w.name as wh_name
        FROM stock_transactions st
        JOIN warehouses w ON st.warehouse_id=w.id
        {where}
        ORDER BY st.trans_date, st.id
        LIMIT {PER_PAGE} OFFSET {(page - 1) * PER_PAGE}
    """
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["type_label"] = REF_TYPE_LABELS.get(r["ref_type"], r["trans_type"])
        r["type_class"] = TRANS_TYPE_CLASS.get(r["trans_type"], "")

    # 기초/합계
    bp = [item_id, date_from]
    bw = ""
    if wh:
        bw = " AND warehouse_id=?"
        bp.append(wh)
    opening = conn.execute(
        f"""SELECT COALESCE(SUM(CASE WHEN trans_type='in' THEN quantity ELSE 0 END)
            - SUM(CASE WHEN trans_type='out' THEN quantity ELSE 0 END), 0)
            FROM stock_transactions WHERE item_id=? AND trans_date < ?{bw}""",
        bp,
    ).fetchone()[0]

    sp = [item_id, date_from, date_to]
    if wh:
        sp.append(wh)
    summary = conn.execute(
        f"""SELECT COALESCE(SUM(CASE WHEN trans_type='in' THEN quantity ELSE 0 END), 0) as total_in,
                   COALESCE(SUM(CASE WHEN trans_type='out' THEN quantity ELSE 0 END), 0) as total_out
            FROM stock_transactions WHERE item_id=? AND trans_date BETWEEN ? AND ?{bw}""",
        sp,
    ).fetchone()

    return templates.TemplateResponse(request=request, name="erp/stock_ledger.html", context={
        "request": request, "page_title": f"수불부 - {item['item_name']}",
        "user_name": u["name"],
        "mode": "detail", "item": item, "rows": rows,
        "opening": opening, "total_in": summary["total_in"], "total_out": summary["total_out"],
        "closing": opening + summary["total_in"] - summary["total_out"],
        "warehouses": warehouses, "wh": wh,
        "date_from": date_from, "date_to": date_to,
        "page": page, "total_pages": total_pages, "total_count": total, "base_url": base_url,
    })
