from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.deps import get_db, templates
from core.task_link import stamp_task
from core.erp_log import log_activity
from core.tz import today_kst
from core import stock
from core.books import require_book

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
                    u: dict = Depends(require_book), conn=Depends(get_db)):
    where = "WHERE company_id=? AND is_active=1"
    params = [u["book"]]
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
async def item_form_new(request: Request, u: dict = Depends(require_book)):
    return templates.TemplateResponse(request=request, name="erp/item_form.html", context={
        "request": request, "page_title": "품목 등록",
        "user_name": u["name"],
        "item": None, "item_types": ITEM_TYPES,
    })


@router.get("/items/{item_id}/edit", response_class=HTMLResponse)
async def item_form_edit(request: Request, item_id: int,
                         u: dict = Depends(require_book), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM items WHERE id=? AND company_id=?", (item_id, u["book"])).fetchone()
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
                    u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    is_new = not bool(item_id)
    if item_id:
        conn.execute(
            """UPDATE items SET item_code=?, item_name=?, item_type=?, unit=?,
               unit_price=?, safety_stock=?, category=? WHERE id=? AND company_id=?""",
            (item_code, item_name, item_type, unit, unit_price, safety_stock, category, item_id, book),
        )
    else:
        task_id = stamp_task(conn, request, u["id"], "master")
        cur = conn.execute(
            """INSERT INTO items (company_id, item_code, item_name, item_type, unit, unit_price, safety_stock, category, created_by, task_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (book, item_code, item_name, item_type, unit, unit_price, safety_stock, category, u["id"], task_id),
        )
        item_id = cur.lastrowid
    if is_new:
        log_activity(conn, u["id"], "create", "master", item_id, item_code, f"품목 등록 {item_name} ({item_code})")
    else:
        log_activity(conn, u["id"], "update", "master", item_id, item_code, f"품목 수정 {item_name} ({item_code})")
    conn.commit()
    return RedirectResponse("/items", status_code=303)


PARTNER_TYPES = {
    "supplier": "공급처",
    "customer": "고객",
    "both": "공급/고객",
}


@router.get("/partners", response_class=HTMLResponse)
async def partner_list(request: Request, q: str = "", ptype: str = "", page: int = 1,
                       include_inactive: int = 0,
                       u: dict = Depends(require_book), conn=Depends(get_db)):
    where = "WHERE company_id=?"
    params = [u["book"]]
    if not include_inactive:
        where += " AND is_active=1"
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
        "partners": rows, "q": q, "ptype": ptype, "include_inactive": include_inactive,
        "partner_types": PARTNER_TYPES,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/partners?q={q}&ptype={ptype}&include_inactive={include_inactive}",
    })


@router.get("/partners/new", response_class=HTMLResponse)
async def partner_form_new(request: Request, u: dict = Depends(require_book)):
    return templates.TemplateResponse(request=request, name="erp/partner_form.html", context={
        "request": request, "page_title": "거래처 등록",
        "user_name": u["name"],
        "partner": None, "partner_types": PARTNER_TYPES,
    })


@router.get("/partners/{partner_id}", response_class=HTMLResponse)
async def partner_detail(request: Request, partner_id: int,
                         u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    row = conn.execute("SELECT * FROM partners WHERE id=? AND company_id=?", (partner_id, book)).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    partner = dict(row)
    partner["type_label"] = PARTNER_TYPES.get(partner.get("partner_type", ""), "공급처")

    match = "(sl.partner_id=? OR (sl.partner_id IS NULL AND sl.partner=?))"
    args = [book, partner_id, partner["name"]]

    ar_bal = conn.execute(
        f"""SELECT COALESCE(SUM(sl.debit),0) - COALESCE(SUM(sl.credit),0)
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE d.company_id=? AND d.status='done' AND {match} AND sl.account_code='110'""",
        args,
    ).fetchone()[0]
    ap_bal = conn.execute(
        f"""SELECT COALESCE(SUM(sl.credit),0) - COALESCE(SUM(sl.debit),0)
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE d.company_id=? AND d.status='done' AND {match} AND sl.account_code='251'""",
        args,
    ).fetchone()[0]

    slips = conn.execute(
        f"""SELECT d.id as doc_id, d.slip_date, d.doc_number, sl.summary, sl.debit, sl.credit
            FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE d.company_id=? AND d.status='done' AND {match}
            ORDER BY d.slip_date DESC, d.id DESC LIMIT 10""",
        args,
    ).fetchall()

    invoices = conn.execute(
        """SELECT id, issue_date, kind, evidence, total FROM tax_invoices
           WHERE company_id=? AND partner_id=? ORDER BY issue_date DESC, id DESC LIMIT 10""",
        (book, partner_id),
    ).fetchall()

    return templates.TemplateResponse(request=request, name="erp/partner_detail.html", context={
        "request": request, "page_title": "거래처 정보",
        "user_name": u["name"],
        "partner": partner,
        "ar_bal": ar_bal, "ap_bal": ap_bal,
        "slips": slips, "invoices": invoices,
    })


@router.get("/partners/{partner_id}/edit", response_class=HTMLResponse)
async def partner_form_edit(request: Request, partner_id: int,
                            u: dict = Depends(require_book), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM partners WHERE id=? AND company_id=?", (partner_id, u["book"])).fetchone()
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
                       code: str = Form(""),
                       name: str = Form(...),
                       partner_type: str = Form("supplier"),
                       biz_no: str = Form(""),
                       representative: str = Form(""),
                       biz_type: str = Form(""),
                       biz_item: str = Form(""),
                       tax_type: str = Form("과세"),
                       address: str = Form(""),
                       phone: str = Form(""),
                       email: str = Form(""),
                       fax: str = Form(""),
                       contact_name: str = Form(""),
                       contact_phone: str = Form(""),
                       contact_email: str = Form(""),
                       notes: str = Form(""),
                       is_active: int = Form(1),
                       u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    if tax_type not in ("과세", "영세", "면세"):
        tax_type = "과세"
    is_new = not bool(partner_id)
    if is_new and not code:
        last = conn.execute(
            "SELECT code FROM partners WHERE company_id=? AND code GLOB '[0-9][0-9][0-9][0-9][0-9]' ORDER BY code DESC LIMIT 1",
            (book,),
        ).fetchone()
        code = f"{(int(last['code']) + 1) if last else 1:05d}"
    if partner_id:
        conn.execute(
            """UPDATE partners SET code=?, name=?, partner_type=?, biz_no=?, representative=?,
               biz_type=?, biz_item=?, tax_type=?, address=?, phone=?, email=?, fax=?,
               contact_name=?, contact_phone=?, contact_email=?, notes=?, is_active=? WHERE id=? AND company_id=?""",
            (code, name, partner_type, biz_no, representative, biz_type, biz_item, tax_type,
             address, phone, email, fax, contact_name, contact_phone, contact_email, notes, is_active, partner_id, book),
        )
        pid = partner_id
    else:
        task_id = stamp_task(conn, request, u["id"], "master")
        cur = conn.execute(
            """INSERT INTO partners (company_id, code, name, partner_type, biz_no, representative,
               biz_type, biz_item, tax_type, address, phone, email, fax,
               contact_name, contact_phone, contact_email, notes, is_active, created_by, task_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (book, code, name, partner_type, biz_no, representative, biz_type, biz_item, tax_type,
             address, phone, email, fax, contact_name, contact_phone, contact_email, notes, is_active, u["id"], task_id),
        )
        pid = cur.lastrowid
    if is_new:
        log_activity(conn, u["id"], "create", "master", pid, biz_no, f"거래처 등록 {name}")
    else:
        log_activity(conn, u["id"], "update", "master", pid, biz_no, f"거래처 수정 {name}")
    conn.commit()
    return RedirectResponse("/partners?saved=1", status_code=303)


@router.get("/bank-accounts", response_class=HTMLResponse)
async def bank_account_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM bank_accounts WHERE company_id=? AND is_active=1 ORDER BY bank, account_no", (u["book"],)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/bank_account_list.html", context={
        "request": request, "page_title": "계좌 관리",
        "user_name": u["name"],
        "accounts": rows,
    })


@router.get("/bank-accounts/new", response_class=HTMLResponse)
async def bank_account_form_new(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    gl_accounts = conn.execute(
        "SELECT code, name FROM accounts WHERE company_id=? AND is_active=1 ORDER BY code", (u["book"],)
    ).fetchall()
    return templates.TemplateResponse(request=request, name="erp/bank_account_form.html", context={
        "request": request, "page_title": "계좌 등록",
        "user_name": u["name"],
        "account": None, "gl_accounts": gl_accounts,
    })


@router.get("/bank-accounts/{account_id}/edit", response_class=HTMLResponse)
async def bank_account_form_edit(request: Request, account_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM bank_accounts WHERE id=? AND company_id=?", (account_id, u["book"])).fetchone()
    if not row:
        return RedirectResponse("/bank-accounts", status_code=303)
    gl_accounts = conn.execute(
        "SELECT code, name FROM accounts WHERE company_id=? AND is_active=1 ORDER BY code", (u["book"],)
    ).fetchall()
    return templates.TemplateResponse(request=request, name="erp/bank_account_form.html", context={
        "request": request, "page_title": "계좌 수정",
        "user_name": u["name"],
        "account": dict(row), "gl_accounts": gl_accounts,
    })


@router.post("/bank-accounts/save", response_class=HTMLResponse)
async def bank_account_save(request: Request,
                            account_id: int = Form(0),
                            bank: str = Form(...),
                            account_no: str = Form(...),
                            name: str = Form(...),
                            account_code: str = Form(...),
                            is_active: int = Form(1),
                            u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    if not conn.execute("SELECT 1 FROM accounts WHERE company_id=? AND code=?", (book, account_code)).fetchone():
        return JSONResponse({"error": "연결 계정을 확인해 주세요."}, status_code=400)
    is_new = not bool(account_id)
    if account_id:
        conn.execute(
            "UPDATE bank_accounts SET bank=?, account_no=?, name=?, account_code=?, is_active=? WHERE id=? AND company_id=?",
            (bank, account_no, name, account_code, is_active, account_id, book),
        )
        aid = account_id
    else:
        cur = conn.execute(
            "INSERT INTO bank_accounts (company_id, bank, account_no, name, account_code, created_by) VALUES (?,?,?,?,?,?)",
            (book, bank, account_no, name, account_code, u["id"]),
        )
        aid = cur.lastrowid
    if is_new:
        log_activity(conn, u["id"], "create", "master", aid, account_no, f"계좌 등록 {bank} {account_no}")
    else:
        log_activity(conn, u["id"], "update", "master", aid, account_no, f"계좌 수정 {bank} {account_no}")
    conn.commit()
    return RedirectResponse("/bank-accounts", status_code=303)


@router.get("/warehouses", response_class=HTMLResponse)
async def warehouse_list(request: Request,
                         u: dict = Depends(require_book), conn=Depends(get_db)):
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code", (u["book"],)
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
async def warehouse_form_new(request: Request, u: dict = Depends(require_book)):
    return templates.TemplateResponse(request=request, name="erp/warehouse_form.html", context={
        "request": request, "page_title": "창고 등록",
        "user_name": u["name"],
        "warehouse": None,
    })


@router.get("/warehouses/{wh_id}/edit", response_class=HTMLResponse)
async def warehouse_form_edit(request: Request, wh_id: int,
                              u: dict = Depends(require_book), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM warehouses WHERE id=? AND company_id=?", (wh_id, u["book"])).fetchone()
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
                         u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    is_new = not bool(wh_id)
    if wh_id:
        conn.execute(
            "UPDATE warehouses SET code=?, name=?, location=? WHERE id=? AND company_id=?",
            (code, name, location, wh_id, book),
        )
    else:
        cur = conn.execute(
            "INSERT INTO warehouses (company_id, code, name, location, created_by) VALUES (?,?,?,?,?)",
            (book, code, name, location, u["id"]),
        )
        wh_id = cur.lastrowid
    if is_new:
        log_activity(conn, u["id"], "create", "master", wh_id, code, f"창고 등록 {name} ({code})")
    else:
        log_activity(conn, u["id"], "update", "master", wh_id, code, f"창고 수정 {name} ({code})")
    conn.commit()
    return RedirectResponse("/warehouses", status_code=303)


@router.get("/memo-codes", response_class=HTMLResponse)
async def memo_code_list(request: Request, q: str = "",
                         u: dict = Depends(require_book), conn=Depends(get_db)):
    where = "WHERE company_id=? AND is_active=1"
    params = [u["book"]]
    if q:
        where += " AND (code LIKE ? OR text LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM memo_codes {where} ORDER BY code", params
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/memo_code_list.html", context={
        "request": request, "page_title": "적요 관리",
        "user_name": u["name"],
        "memos": rows, "q": q,
    })


@router.get("/memo-codes/new", response_class=HTMLResponse)
async def memo_code_form_new(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    gl_accounts = conn.execute(
        "SELECT code, name FROM accounts WHERE company_id=? AND is_active=1 ORDER BY code", (u["book"],)
    ).fetchall()
    return templates.TemplateResponse(request=request, name="erp/memo_code_form.html", context={
        "request": request, "page_title": "적요 등록",
        "user_name": u["name"],
        "memo": None, "gl_accounts": gl_accounts,
    })


@router.get("/memo-codes/{memo_id}/edit", response_class=HTMLResponse)
async def memo_code_form_edit(request: Request, memo_id: int,
                              u: dict = Depends(require_book), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM memo_codes WHERE id=? AND company_id=?", (memo_id, u["book"])).fetchone()
    if not row:
        return RedirectResponse("/memo-codes", status_code=303)
    gl_accounts = conn.execute(
        "SELECT code, name FROM accounts WHERE company_id=? AND is_active=1 ORDER BY code", (u["book"],)
    ).fetchall()
    return templates.TemplateResponse(request=request, name="erp/memo_code_form.html", context={
        "request": request, "page_title": "적요 수정",
        "user_name": u["name"],
        "memo": dict(row), "gl_accounts": gl_accounts,
    })


@router.post("/memo-codes/save", response_class=HTMLResponse)
async def memo_code_save(request: Request,
                         memo_id: int = Form(0),
                         code: str = Form(...),
                         text: str = Form(...),
                         account_code: str = Form(""),
                         is_active: int = Form(1),
                         u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    account_code = account_code or None
    is_new = not bool(memo_id)
    if memo_id:
        conn.execute(
            "UPDATE memo_codes SET code=?, text=?, account_code=?, is_active=? WHERE id=? AND company_id=?",
            (code, text, account_code, is_active, memo_id, book),
        )
        mid = memo_id
    else:
        cur = conn.execute(
            "INSERT INTO memo_codes (company_id, code, text, account_code, created_by) VALUES (?,?,?,?,?)",
            (book, code, text, account_code, u["id"]),
        )
        mid = cur.lastrowid
    if is_new:
        log_activity(conn, u["id"], "create", "master", mid, code, f"적요 등록 {code} ({text})")
    else:
        log_activity(conn, u["id"], "update", "master", mid, code, f"적요 수정 {code} ({text})")
    conn.commit()
    return RedirectResponse("/memo-codes?saved=1", status_code=303)


@router.get("/api/memo_codes")
async def api_memo_codes(q: str = "", account: str = "",
                         u: dict = Depends(require_book), conn=Depends(get_db)):
    where = "WHERE company_id=? AND is_active=1"
    params = [u["book"]]
    if q:
        where += " AND (code LIKE ? OR text LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if account:
        where += " AND account_code=?"
        params.append(account)
    rows = conn.execute(
        f"SELECT id, code, text AS name, account_code FROM memo_codes {where} ORDER BY code", params
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/stock", response_class=HTMLResponse)
async def stock_list(request: Request, q: str = "", wh: int = 0, low: int = 0, page: int = 1,
                     u: dict = Depends(require_book), conn=Depends(get_db)):
    base_where = "WHERE i.company_id=? AND i.is_active=1 AND w.is_active=1"
    params = [u["book"]]
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
        "SELECT id, code, name FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code", (u["book"],)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/stock_list.html", context={
        "request": request, "page_title": "재고 현황",
        "user_name": u["name"],
        "stocks": rows, "q": q, "wh": wh, "low": low,
        "warehouses": warehouses, "item_types": ITEM_TYPES,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/stock?q={q}&wh={wh}&low={low}",
    })


@router.get("/stock/valuation", response_class=HTMLResponse)
async def stock_valuation(request: Request, date_to: str = "",
                          u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    date_to = date_to or today_kst().isoformat()
    rows = stock.valuation(conn, book, date_to)
    for r in rows:
        r["avg"] = round(r["amt"] / r["qty"]) if r["qty"] else None
    total = sum(r["amt"] for r in rows)
    gl = conn.execute(
        """SELECT COALESCE(SUM(sl.debit - sl.credit), 0) FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
           WHERE d.company_id=? AND d.status='done' AND d.slip_date<=? AND sl.account_code='120'""",
        (book, date_to),
    ).fetchone()[0]
    return templates.TemplateResponse(request=request, name="erp/stock_valuation.html", context={
        "request": request, "page_title": "재고평가",
        "user_name": u["name"],
        "rows": rows, "total": total, "gl": gl, "date_to": date_to,
    })


REF_TYPE_LABELS = {
    "open": "기초재고",
    "gr": "입고",
    "ship": "출고",
    "wo_material": "생산출고",
    "wo_product": "생산입고",
    "adj": "재고조정",
    "transfer": "재고이동",
}

TRANS_TYPE_CLASS = {
    "in": "bg-success",
    "out": "bg-danger",
    "adjust": "bg-warning text-dark",
}


@router.get("/stock/ledger", response_class=HTMLResponse)
async def stock_ledger(request: Request, item_id: int = 0, wh: int = 0,
                       date_from: str = "", date_to: str = "", page: int = 1,
                       u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code", (book,)
    ).fetchall()]

    if not date_from:
        date_from = f"{today_kst().year}-01-01"
    if not date_to:
        date_to = today_kst().isoformat()

    base_url = f"/stock/ledger?item_id={item_id}&wh={wh}&date_from={date_from}&date_to={date_to}"

    if not item_id:
        where = "WHERE i.company_id=? AND st.trans_date BETWEEN ? AND ?"
        params = [book, date_from, date_to]
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
    item = conn.execute("SELECT * FROM items WHERE id=? AND company_id=?", (item_id, book)).fetchone()
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
