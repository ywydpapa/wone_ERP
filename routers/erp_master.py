from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from core.deps import get_db, require_login, templates

router = APIRouter()

ITEM_TYPES = {
    "material": "원재료",
    "product": "완제품",
    "semi": "반제품",
    "consumable": "소모품",
}


@router.get("/items", response_class=HTMLResponse)
async def item_list(request: Request, q: str = "", item_type: str = "",
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    sql = "SELECT * FROM items WHERE is_active=1"
    params = []
    if q:
        sql += " AND (item_code LIKE ? OR item_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if item_type:
        sql += " AND item_type=?"
        params.append(item_type)
    sql += " ORDER BY item_code"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["item_type_label"] = ITEM_TYPES.get(r["item_type"], r["item_type"])
    return templates.TemplateResponse(request=request, name="erp/item_list.html", context={
        "request": request, "page_title": "품목 관리",
        "user_name": u["user_name"],
        "items": rows, "q": q, "item_type": item_type,
        "item_types": ITEM_TYPES,
    })


@router.get("/items/new", response_class=HTMLResponse)
async def item_form_new(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="erp/item_form.html", context={
        "request": request, "page_title": "품목 등록",
        "user_name": u["user_name"],
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
        "user_name": u["user_name"],
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
async def partner_list(request: Request, q: str = "", ptype: str = "",
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    sql = "SELECT * FROM partners WHERE is_active=1"
    params = []
    if q:
        sql += " AND (code LIKE ? OR name LIKE ? OR biz_no LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if ptype:
        sql += " AND partner_type=?"
        params.append(ptype)
    sql += " ORDER BY code"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["type_label"] = PARTNER_TYPES.get(r.get("partner_type", ""), "공급처")
    return templates.TemplateResponse(request=request, name="erp/partner_list.html", context={
        "request": request, "page_title": "거래처 관리",
        "user_name": u["user_name"],
        "partners": rows, "q": q, "ptype": ptype,
        "partner_types": PARTNER_TYPES,
    })


@router.get("/partners/new", response_class=HTMLResponse)
async def partner_form_new(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="erp/partner_form.html", context={
        "request": request, "page_title": "거래처 등록",
        "user_name": u["user_name"],
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
        "user_name": u["user_name"],
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
        "user_name": u["user_name"],
        "warehouses": rows,
    })


@router.get("/warehouses/new", response_class=HTMLResponse)
async def warehouse_form_new(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="erp/warehouse_form.html", context={
        "request": request, "page_title": "창고 등록",
        "user_name": u["user_name"],
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
        "user_name": u["user_name"],
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
async def stock_list(request: Request, q: str = "", wh: int = 0, low: int = 0,
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    sql = """
        SELECT s.id, s.quantity, i.item_code, i.item_name, i.item_type, i.unit,
               i.safety_stock, w.code as wh_code, w.name as wh_name, i.id as item_id
        FROM stock s
        JOIN items i ON s.item_id=i.id
        JOIN warehouses w ON s.warehouse_id=w.id
        WHERE i.is_active=1 AND w.is_active=1
    """
    params = []
    if q:
        sql += " AND (i.item_code LIKE ? OR i.item_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if wh:
        sql += " AND s.warehouse_id=?"
        params.append(wh)
    if low:
        sql += " AND s.quantity <= i.safety_stock"
    sql += " ORDER BY i.item_code, w.code"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["item_type_label"] = ITEM_TYPES.get(r["item_type"], r["item_type"])
        r["is_low"] = r["quantity"] <= r["safety_stock"]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE is_active=1 ORDER BY code"
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/stock_list.html", context={
        "request": request, "page_title": "재고 현황",
        "user_name": u["user_name"],
        "stocks": rows, "q": q, "wh": wh, "low": low,
        "warehouses": warehouses, "item_types": ITEM_TYPES,
    })
