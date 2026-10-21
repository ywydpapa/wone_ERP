import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core import audit, books, stock
from core.books import require_book
from core.deps import get_db, templates
from core.erp_log import log_activity
from core.export import csv_response
from core.tz import today_kst

router = APIRouter()
PER_PAGE = 20

STOCK_SORTS = {"number": "m.move_number", "date": "m.move_date", "wh": "w.name", "reason": "m.reason",
               "to_wh": "t.name", "cnt": "cnt"}

KINDS = {
    "adjust": {"title": "재고조정", "url": "/stock/adjustments", "prefix": "ADJ", "ref": "adj"},
    "transfer": {"title": "재고이동", "url": "/stock/transfers", "prefix": "TR", "ref": "transfer"},
}
# 실사조정은 차액을 매출원가로 대체. 기초재고는 장부 기초잔액이 따로 있음. 전표 없음
REASONS = ("실사조정", "기초재고")


def _num(v):
    v = str(v or "").replace(",", "").strip()
    if not v:
        return None
    if not v.lstrip("-").isdigit():
        raise ValueError
    return int(v)


def _wh(conn, book, wh_id):
    return conn.execute(
        "SELECT id, code, name FROM warehouses WHERE id=? AND company_id=? AND is_active=1", (wh_id, book)
    ).fetchone()


def _items(conn, book, wh_id, only_stock=False):
    sql = """SELECT i.id, i.item_code, i.item_name, i.unit, i.stock_amt,
                    COALESCE(s.quantity, 0) AS qty,
                    (SELECT COALESCE(SUM(quantity), 0) FROM stock WHERE item_id=i.id) AS total
             FROM items i LEFT JOIN stock s ON s.item_id=i.id AND s.warehouse_id=?
             WHERE i.company_id=? AND i.is_active=1"""
    if only_stock:
        sql += " AND s.quantity > 0"
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY i.item_code", (wh_id, book)).fetchall()]
    for r in rows:
        r["avg"] = round(r["stock_amt"] / r["total"]) if r["total"] > 0 else 0
    return rows


def _insert(conn, book, kind, date, wh_id, to_wh, reason, notes, uid):
    prefix = f"{KINDS[kind]['prefix']}-{date[:4]}-"
    row = conn.execute(
        "SELECT move_number FROM stock_moves WHERE move_number LIKE ? ORDER BY id DESC LIMIT 1", (prefix + "%",)
    ).fetchone()
    seq = int(row[0].split("-")[-1]) + 1 if row else 1
    while True:
        try:
            return conn.execute(
                """INSERT INTO stock_moves (company_id, kind, move_number, move_date, warehouse_id, to_wh_id,
                       reason, notes, created_by) VALUES (?,?,?,?,?,?,?,?,?)""",
                (book, kind, f"{prefix}{seq:04d}", date, wh_id, to_wh, reason, notes, uid),
            ).lastrowid
        except sqlite3.IntegrityError:
            seq += 1


def _list(request, u, conn, kind, page, sort, dir, export):
    order = STOCK_SORTS.get(sort)
    order_sql = f"ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, m.id DESC" if order else "ORDER BY m.move_date DESC, m.id DESC"
    sql = """SELECT m.*, w.name AS wh_name, t.name AS to_wh_name, u.name AS creator,
                  (SELECT COUNT(DISTINCT st.item_id) FROM stock_transactions st
                   WHERE st.ref_type=? AND st.ref_id=m.id) AS cnt
           FROM stock_moves m JOIN warehouses w ON w.id=m.warehouse_id
           LEFT JOIN warehouses t ON t.id=m.to_wh_id LEFT JOIN users u ON u.id=m.created_by
           WHERE m.company_id=? AND m.kind=?"""
    params = [KINDS[kind]["ref"], u["book"], kind]

    if export == "csv":
        rows = [dict(r) for r in conn.execute(f"{sql} {order_sql}", params).fetchall()]
        if kind == "adjust":
            headers = ["번호", "일자", "창고", "사유", "품목수", "비고", "작성자"]
            data = [[r["move_number"], r["move_date"], r["wh_name"], r["reason"], r["cnt"],
                     r["notes"] or "", r["creator"] or ""] for r in rows]
        else:
            headers = ["번호", "일자", "출고창고", "입고창고", "품목수", "비고", "작성자"]
            data = [[r["move_number"], r["move_date"], r["wh_name"], r["to_wh_name"], r["cnt"],
                     r["notes"] or "", r["creator"] or ""] for r in rows]
        return csv_response(headers, data, f"stock_{kind}.csv")

    total = conn.execute(
        "SELECT COUNT(*) FROM stock_moves WHERE company_id=? AND kind=?", (u["book"], kind)
    ).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    rows = [dict(r) for r in conn.execute(
        f"{sql} {order_sql} LIMIT ? OFFSET ?", (*params, PER_PAGE, (page - 1) * PER_PAGE)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/stock_move_list.html", context={
        "request": request, "page_title": KINDS[kind]["title"], "user_name": u["name"],
        "kind": kind, "k": KINDS[kind], "rows": rows,
        "page": page, "total_pages": total_pages,
        "base_url": f"{KINDS[kind]['url']}?sort={sort}&dir={dir}",
        "sort": sort, "dir": dir,
    })


def _form(request, u, conn, kind, wh_id):
    book = u["book"]
    warehouses = [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM warehouses WHERE company_id=? AND is_active=1 ORDER BY code", (book,)
    ).fetchall()]
    wh = _wh(conn, book, wh_id) if wh_id else None
    return templates.TemplateResponse(request=request, name="erp/stock_move_form.html", context={
        "request": request, "page_title": f"{KINDS[kind]['title']} 입력", "user_name": u["name"],
        "kind": kind, "k": KINDS[kind], "warehouses": warehouses, "wh": wh, "reasons": REASONS,
        "items": _items(conn, book, wh_id, kind == "transfer") if wh else [],
        "today": today_kst().isoformat(),
    })


def _detail(request, u, conn, kind, move_id):
    m = conn.execute(
        """SELECT m.*, w.name AS wh_name, t.name AS to_wh_name, u.name AS creator, d.slip_no
           FROM stock_moves m JOIN warehouses w ON w.id=m.warehouse_id
           LEFT JOIN warehouses t ON t.id=m.to_wh_id LEFT JOIN users u ON u.id=m.created_by
           LEFT JOIN erp_docs d ON d.id=m.doc_id
           WHERE m.id=? AND m.company_id=? AND m.kind=?""",
        (move_id, u["book"], kind),
    ).fetchone()
    if not m:
        return RedirectResponse(KINDS[kind]["url"], status_code=303)
    lines = [dict(r) for r in conn.execute(
        """SELECT st.*, i.item_code, i.item_name, i.unit, w.name AS wh_name
           FROM stock_transactions st JOIN items i ON i.id=st.item_id JOIN warehouses w ON w.id=st.warehouse_id
           WHERE st.ref_type=? AND st.ref_id=? ORDER BY st.id""",
        (KINDS[kind]["ref"], move_id),
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/stock_move_detail.html", context={
        "request": request, "page_title": f"{KINDS[kind]['title']} {m['move_number']}", "user_name": u["name"],
        "kind": kind, "k": KINDS[kind], "m": dict(m), "lines": lines,
    })


@router.get("/stock/adjustments", response_class=HTMLResponse)
async def adj_list(request: Request, page: int = 1, sort: str = "", dir: str = "", export: str = "",
                   u: dict = Depends(require_book), conn=Depends(get_db)):
    return _list(request, u, conn, "adjust", page, sort, dir, export)


@router.get("/stock/adjustments/new", response_class=HTMLResponse)
async def adj_new(request: Request, wh: int = 0, u: dict = Depends(require_book), conn=Depends(get_db)):
    return _form(request, u, conn, "adjust", wh)


@router.get("/stock/adjustments/{move_id}", response_class=HTMLResponse)
async def adj_detail(request: Request, move_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    return _detail(request, u, conn, "adjust", move_id)


@router.post("/stock/adjustments")
async def adj_save(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    form = await request.form()
    book, uid = u["book"], u["id"]
    date = form.get("move_date") or today_kst().isoformat()
    reason = form.get("reason") if form.get("reason") in REASONS else REASONS[0]
    wh = _wh(conn, book, int(form.get("warehouse_id") or 0))
    if not wh:
        return JSONResponse({"error": "창고를 선택해 주세요."}, status_code=400)
    if books.period_closed(conn, book, date):
        return JSONResponse({"error": "마감된 회계기간입니다."}, status_code=400)

    rows = []
    for it in _items(conn, book, wh["id"]):
        try:
            count = _num(form.get(f"count_{it['id']}"))
            price = _num(form.get(f"price_{it['id']}"))
        except ValueError:
            return JSONResponse({"error": f"수량/단가는 숫자로 입력해 주세요. ({it['item_name']})"}, status_code=400)
        if count is None or count == it["qty"]:
            continue
        if count < 0 or (price is not None and price < 0):
            return JSONResponse({"error": f"음수는 입력할 수 없습니다. ({it['item_name']})"}, status_code=400)
        rows.append((it["id"], count - it["qty"], price))
    if not rows:
        return JSONResponse({"error": "실사수량이 바뀐 품목이 없습니다."}, status_code=400)

    move_id = _insert(conn, book, "adjust", date, wh["id"], None, reason, form.get("notes", ""), uid)
    net = 0
    try:
        for item_id, diff, price in rows:
            if diff > 0:
                net += stock.move_in(conn, item_id, wh["id"], diff, date, "adj", move_id, uid, price)
            else:
                net -= stock.move_out(conn, item_id, wh["id"], -diff, date, "adj", move_id, uid)
        if reason == "실사조정" and net:
            summary = f"재고실사 차이 {wh['name']}"
            code_dr, code_cr = ("120", "451") if net > 0 else ("451", "120")
            doc_id = books.post(conn, book, uid, date, [
                {"code": code_dr, "debit": abs(net), "credit": 0, "summary": summary},
                {"code": code_cr, "debit": 0, "credit": abs(net), "summary": summary},
            ], f"재고조정 전표 ({wh['name']})", "adj", move_id)
            conn.execute("UPDATE stock_moves SET doc_id=? WHERE id=?", (doc_id, move_id))
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    log_activity(conn, uid, "create", "inventory", move_id, "", f"재고조정 {wh['name']} {len(rows)}건")
    audit.log(conn, uid, "stock_adjust", "stock_adj", move_id, f"{wh['name']} {len(rows)}건", company_id=book)
    conn.commit()
    return RedirectResponse(f"/stock/adjustments/{move_id}", status_code=303)


@router.get("/stock/transfers", response_class=HTMLResponse)
async def tr_list(request: Request, page: int = 1, sort: str = "", dir: str = "", export: str = "",
                  u: dict = Depends(require_book), conn=Depends(get_db)):
    return _list(request, u, conn, "transfer", page, sort, dir, export)


@router.get("/stock/transfers/new", response_class=HTMLResponse)
async def tr_new(request: Request, wh: int = 0, u: dict = Depends(require_book), conn=Depends(get_db)):
    return _form(request, u, conn, "transfer", wh)


@router.get("/stock/transfers/{move_id}", response_class=HTMLResponse)
async def tr_detail(request: Request, move_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    return _detail(request, u, conn, "transfer", move_id)


@router.post("/stock/transfers")
async def tr_save(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    form = await request.form()
    book, uid = u["book"], u["id"]
    date = form.get("move_date") or today_kst().isoformat()
    src = _wh(conn, book, int(form.get("warehouse_id") or 0))
    dst = _wh(conn, book, int(form.get("to_wh_id") or 0))
    if not src or not dst:
        return JSONResponse({"error": "출고/입고 창고를 선택해 주세요."}, status_code=400)
    if src["id"] == dst["id"]:
        return JSONResponse({"error": "같은 창고로는 이동할 수 없습니다."}, status_code=400)
    if books.period_closed(conn, book, date):
        return JSONResponse({"error": "마감된 회계기간입니다."}, status_code=400)

    rows = []
    for it in _items(conn, book, src["id"], True):
        try:
            qty = _num(form.get(f"qty_{it['id']}"))
        except ValueError:
            return JSONResponse({"error": f"수량은 숫자로 입력해 주세요. ({it['item_name']})"}, status_code=400)
        if qty:
            if qty < 0:
                return JSONResponse({"error": f"음수는 입력할 수 없습니다. ({it['item_name']})"}, status_code=400)
            rows.append((it["id"], qty))
    if not rows:
        return JSONResponse({"error": "이동 수량을 입력해 주세요."}, status_code=400)

    move_id = _insert(conn, book, "transfer", date, src["id"], dst["id"], "", form.get("notes", ""), uid)
    try:
        for item_id, qty in rows:
            # 이동은 금액 그대로 옮겨 평균단가 불변
            amt = stock.move_out(conn, item_id, src["id"], qty, date, "transfer", move_id, uid)
            stock.move_in(conn, item_id, dst["id"], qty, date, "transfer", move_id, uid, amt / qty)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    log_activity(conn, uid, "create", "inventory", move_id, "", f"재고이동 {src['name']} -> {dst['name']} {len(rows)}건")
    conn.commit()
    return RedirectResponse(f"/stock/transfers/{move_id}", status_code=303)
