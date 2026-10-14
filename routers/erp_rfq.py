import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core import audit, books
from core.approval import current_line, insert_lines, parse_lines, preset_lines
from core.books import require_book
from core.deps import get_db, templates
from core.erp_log import log_activity
from core.notification import create_notification
from core.tz import now_kst, today_kst
from routers.erp_master import _suppliers
from routers.erp_purchase import _next_po_number

router = APIRouter()
PER_PAGE = 20

RFQ_STATUS = {"open": "견적중", "pending": "낙찰결재", "ordered": "발주완료", "cancelled": "취소"}
RFQ_STATUS_CLASS = {
    "open": "status-badge status-wait",
    "pending": "status-badge status-progress",
    "ordered": "status-badge status-done",
    "cancelled": "status-badge status-reject",
}


def _num(v):
    v = str(v or "").replace(",", "").strip()
    return int(v) if v.isdigit() else None


def _rfq(conn, book, rfq_id):
    row = conn.execute(
        """SELECT r.*, pr.pr_number, d.status AS doc_status, d.doc_number, po.po_number, p.name AS partner_name
           FROM rfqs r LEFT JOIN purchase_requisitions pr ON pr.id=r.pr_id
           LEFT JOIN erp_docs d ON d.id=r.doc_id LEFT JOIN purchase_orders po ON po.id=r.po_id
           LEFT JOIN partners p ON p.id=r.partner_id
           WHERE r.id=? AND r.company_id=?""", (rfq_id, book)
    ).fetchone()
    return dict(row) if row else None


def _compare(conn, rfq_id):
    lines = [dict(r) for r in conn.execute(
        """SELECT l.*, i.item_code, i.item_name, i.unit FROM rfq_lines l JOIN items i ON i.id=l.item_id
           WHERE l.rfq_id=? ORDER BY l.line_no""", (rfq_id,)
    ).fetchall()]
    vendors = [dict(r) for r in conn.execute(
        """SELECT v.*, p.code, p.name FROM rfq_vendors v JOIN partners p ON p.id=v.partner_id
           WHERE v.rfq_id=? ORDER BY p.code""", (rfq_id,)
    ).fetchall()]
    quotes = {(q["vendor_id"], q["line_id"]): q["price"] for q in conn.execute(
        "SELECT q.* FROM rfq_quotes q JOIN rfq_lines l ON l.id=q.line_id WHERE l.rfq_id=?", (rfq_id,)
    )}
    for v in vendors:
        v["prices"] = [quotes.get((v["id"], l["id"])) for l in lines]
        v["full"] = None not in v["prices"]
        v["total"] = sum((p or 0) * l["quantity"] for p, l in zip(v["prices"], lines))
    best = min((v["total"] for v in vendors if v["full"]), default=None)
    for v in vendors:
        v["best"] = v["full"] and v["total"] == best
    for i, l in enumerate(lines):
        low = min((v["prices"][i] for v in vendors if v["prices"][i] is not None), default=None)
        l["quotes"] = [{"vid": v["id"], "vname": v["name"], "price": v["prices"][i],
                        "low": v["prices"][i] is not None and v["prices"][i] == low} for v in vendors]
    return lines, vendors


@router.get("/rfqs", response_class=HTMLResponse)
async def rfq_list(request: Request, status: str = "", page: int = 1,
                   u: dict = Depends(require_book), conn=Depends(get_db)):
    where, params = "WHERE r.company_id=?", [u["book"]]
    if status:
        where += " AND r.status=?"
        params.append(status)
    total = conn.execute(f"SELECT COUNT(*) FROM rfqs r {where}", params).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    rows = [dict(r) for r in conn.execute(
        f"""SELECT r.*, pr.pr_number, p.name AS partner_name,
                   (SELECT COUNT(*) FROM rfq_vendors WHERE rfq_id=r.id) AS vendor_cnt,
                   (SELECT COUNT(DISTINCT q.vendor_id) FROM rfq_quotes q JOIN rfq_vendors v ON v.id=q.vendor_id
                    WHERE v.rfq_id=r.id) AS quoted_cnt
            FROM rfqs r LEFT JOIN purchase_requisitions pr ON pr.id=r.pr_id LEFT JOIN partners p ON p.id=r.partner_id
            {where} ORDER BY r.id DESC LIMIT {PER_PAGE} OFFSET {(page - 1) * PER_PAGE}""", params
    ).fetchall()]
    for r in rows:
        r["status_label"] = RFQ_STATUS[r["status"]]
        r["status_class"] = RFQ_STATUS_CLASS[r["status"]]
    return templates.TemplateResponse(request=request, name="erp/rfq_list.html", context={
        "request": request, "page_title": "견적요청 현황", "user_name": u["name"],
        "rows": rows, "status": status, "rfq_status": RFQ_STATUS,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/rfqs?status={status}",
    })


@router.get("/rfqs/new", response_class=HTMLResponse)
async def rfq_new(request: Request, pr_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    pr = conn.execute(
        "SELECT * FROM purchase_requisitions WHERE id=? AND company_id=? AND status='approved'", (pr_id, book)
    ).fetchone()
    if not pr:
        return RedirectResponse("/purchase-requisitions", status_code=303)
    lines = [dict(r) for r in conn.execute(
        """SELECT pl.*, i.item_code, i.unit FROM pr_lines pl LEFT JOIN items i ON i.id=pl.item_id
           WHERE pl.pr_id=? ORDER BY pl.line_no""", (pr_id,)
    ).fetchall()]
    item_ids = [l["item_id"] for l in lines if l["item_id"]]
    defaults = {r[0] for r in conn.execute(
        f"SELECT partner_id FROM items WHERE id IN ({','.join('?' * len(item_ids))})", item_ids
    ) if r[0]} if item_ids else set()
    return templates.TemplateResponse(request=request, name="erp/rfq_form.html", context={
        "request": request, "page_title": "견적요청 작성", "user_name": u["name"],
        "pr": dict(pr), "lines": lines, "suppliers": _suppliers(conn, book), "defaults": defaults,
        "today": today_kst().isoformat(),
    })


@router.post("/rfqs")
async def rfq_create(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    form = await request.form()
    book = u["book"]
    pr_id = _num(form.get("pr_id")) or 0
    pr = conn.execute(
        "SELECT * FROM purchase_requisitions WHERE id=? AND company_id=? AND status='approved'", (pr_id, book)
    ).fetchone()
    if not pr:
        return JSONResponse({"error": "승인된 구매요청만 견적요청할 수 있습니다."}, status_code=400)
    lines = conn.execute("SELECT * FROM pr_lines WHERE pr_id=? ORDER BY line_no", (pr_id,)).fetchall()
    if any(not l["item_id"] for l in lines):
        return JSONResponse({"error": "품목이 지정되지 않은 요청 품목이 있습니다. 구매요청을 수정해 주세요."}, status_code=400)
    vendor_ids = {int(v) for v in form.getlist("partner_id") if v.isdigit()}
    vendors = [r[0] for r in conn.execute(
        f"""SELECT id FROM partners WHERE company_id=? AND partner_type IN ('supplier','both')
            AND id IN ({','.join('?' * len(vendor_ids))})""", (book, *vendor_ids)
    )] if vendor_ids else []
    if not vendors or len(vendors) != len(vendor_ids):
        return JSONResponse({"error": "견적 요청할 거래처를 선택해 주세요."}, status_code=400)
    rfq_date = form.get("rfq_date") or today_kst().isoformat()
    due_date = form.get("due_date", "")
    try:
        date.fromisoformat(rfq_date)
        if due_date:
            date.fromisoformat(due_date)
    except ValueError:
        return JSONResponse({"error": "날짜를 확인해 주세요."}, status_code=400)

    prefix = f"RFQ-{rfq_date[:4]}-"
    row = conn.execute(
        "SELECT rfq_number FROM rfqs WHERE rfq_number LIKE ? ORDER BY id DESC LIMIT 1", (prefix + "%",)
    ).fetchone()
    seq = int(row[0].split("-")[-1]) + 1 if row else 1
    while True:
        try:
            rfq_id = conn.execute(
                """INSERT INTO rfqs (company_id, rfq_number, pr_id, rfq_date, due_date, notes, created_by)
                   VALUES (?,?,?,?,?,?,?)""",
                (book, f"{prefix}{seq:04d}", pr_id, rfq_date, due_date, form.get("notes", ""), u["id"]),
            ).lastrowid
            break
        except sqlite3.IntegrityError:
            seq += 1
    for l in lines:
        conn.execute("INSERT INTO rfq_lines (rfq_id, line_no, item_id, quantity) VALUES (?,?,?,?)",
                     (rfq_id, l["line_no"], l["item_id"], l["quantity"]))
    for pid in vendors:
        conn.execute("INSERT INTO rfq_vendors (rfq_id, partner_id) VALUES (?,?)", (rfq_id, pid))
    conn.execute("UPDATE purchase_requisitions SET status='rfq' WHERE id=?", (pr_id,))
    number = f"{prefix}{seq:04d}"
    log_activity(conn, u["id"], "create", "purchase", rfq_id, number, f"견적요청 {number} ({pr['pr_number']}, {len(vendors)}곳)")
    conn.commit()
    return RedirectResponse(f"/rfqs/{rfq_id}", status_code=303)


@router.get("/rfqs/{rfq_id}", response_class=HTMLResponse)
async def rfq_detail(request: Request, rfq_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    rfq = _rfq(conn, book, rfq_id)
    if not rfq:
        return RedirectResponse("/rfqs", status_code=303)
    rfq["status_label"] = RFQ_STATUS[rfq["status"]]
    rfq["status_class"] = RFQ_STATUS_CLASS[rfq["status"]]
    lines, vendors = _compare(conn, rfq_id)
    pending = rfq["status"] == "pending"
    return templates.TemplateResponse(request=request, name="erp/rfq_detail.html", context={
        "request": request, "page_title": f"견적요청 {rfq['rfq_number']}", "user_name": u["name"],
        "rfq": rfq, "lines": lines, "vendors": vendors,
        "can_quote": rfq["status"] == "open",
        "can_award": rfq["status"] == "open" or (pending and rfq["doc_status"] == "rejected"),
        "can_order": pending and rfq["doc_status"] == "done",
        "users": [x for x in books.book_users(conn, book) if x["id"] != u["id"]],
        "preset": preset_lines(conn, book, "draft"), "drafter": u["name"],
        "today": today_kst().isoformat(),
    })


@router.post("/rfqs/{rfq_id}/quotes/{vendor_id}")
async def rfq_quote(request: Request, rfq_id: int, vendor_id: int,
                    u: dict = Depends(require_book), conn=Depends(get_db)):
    rfq = _rfq(conn, u["book"], rfq_id)
    vendor = conn.execute(
        "SELECT v.id, p.name FROM rfq_vendors v JOIN partners p ON p.id=v.partner_id WHERE v.id=? AND v.rfq_id=?",
        (vendor_id, rfq_id),
    ).fetchone()
    if not rfq or not vendor:
        return JSONResponse({"error": "견적요청을 찾을 수 없습니다."}, status_code=404)
    if rfq["status"] != "open":
        return JSONResponse({"error": "견적 입력이 끝난 요청입니다."}, status_code=400)
    form = await request.form()
    lines = conn.execute("SELECT id FROM rfq_lines WHERE rfq_id=?", (rfq_id,)).fetchall()
    prices = {}
    for l in lines:
        raw = str(form.get(f"price_{l['id']}", "")).strip()
        if raw == "":
            continue
        p = _num(raw)
        if p is None:
            return JSONResponse({"error": "단가는 0 이상 숫자로 입력해 주세요."}, status_code=400)
        prices[l["id"]] = p
    lead = _num(form.get("lead_days") or "0")
    valid_to = form.get("valid_to", "")
    try:
        if valid_to:
            date.fromisoformat(valid_to)
    except ValueError:
        return JSONResponse({"error": "견적 유효일을 확인해 주세요."}, status_code=400)
    if lead is None:
        return JSONResponse({"error": "납기(일)는 0 이상 숫자로 입력해 주세요."}, status_code=400)
    conn.execute("DELETE FROM rfq_quotes WHERE vendor_id=?", (vendor_id,))
    conn.executemany("INSERT INTO rfq_quotes (vendor_id, line_id, price) VALUES (?,?,?)",
                     [(vendor_id, lid, p) for lid, p in prices.items()])
    conn.execute(
        "UPDATE rfq_vendors SET quote_date=?, valid_to=?, lead_days=?, notes=? WHERE id=?",
        (form.get("quote_date") or today_kst().isoformat(), valid_to, lead, form.get("notes", ""), vendor_id),
    )
    log_activity(conn, u["id"], "update", "purchase", rfq_id, rfq["rfq_number"],
                 f"견적 입력 {rfq['rfq_number']} ({vendor['name']})")
    conn.commit()
    return RedirectResponse(f"/rfqs/{rfq_id}", status_code=303)


@router.post("/rfqs/{rfq_id}/award")
async def rfq_award(request: Request, rfq_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    book, uid = u["book"], u["id"]
    rfq = _rfq(conn, book, rfq_id)
    if not rfq:
        return JSONResponse({"error": "견적요청을 찾을 수 없습니다."}, status_code=404)
    if not (rfq["status"] == "open" or (rfq["status"] == "pending" and rfq["doc_status"] == "rejected")):
        return JSONResponse({"error": "낙찰 결재를 올릴 수 없는 상태입니다."}, status_code=400)
    form = await request.form()
    lines, vendors = _compare(conn, rfq_id)
    vid = _num(form.get("vendor_id"))
    vendor = next((v for v in vendors if v["id"] == vid), None)
    if not vendor or not vendor["full"]:
        return JSONResponse({"error": "모든 품목의 견적이 입력된 거래처만 낙찰할 수 있습니다."}, status_code=400)
    users = {x["id"] for x in books.book_users(conn, book) if x["id"] != uid}
    appr, err = parse_lines(form, users)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    reason = form.get("reason", "").strip()
    if not vendor["best"] and not reason:
        return JSONResponse({"error": "최저가가 아닌 거래처는 선정 사유를 입력해 주세요."}, status_code=400)

    rows = "\n".join(f"- {v['name']}: {v['total']:,}원{' (미완료)' if not v['full'] else ''}" for v in vendors)
    content = (f"견적요청 {rfq['rfq_number']} (구매요청 {rfq['pr_number'] or '-'}) 낙찰 품의\n"
               f"낙찰 거래처: {vendor['name']}, 공급가액 {vendor['total']:,}원\n\n비교 견적\n{rows}")
    if reason:
        content += f"\n\n선정 사유: {reason}"
    title = f"낙찰 품의 {rfq['rfq_number']} {vendor['name']}"
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    doc_id = conn.execute(
        """INSERT INTO erp_docs (user_id, doc_type, title, content, status, company_id, source_type, source_id)
           VALUES (?, 'draft', ?, ?, 'wait', ?, 'rfq', ?)""",
        (uid, title, content, book, rfq_id),
    ).lastrowid
    doc_number = f"GW-{now_kst().year}-{doc_id:04d}"
    conn.execute("UPDATE erp_docs SET doc_number=? WHERE id=?", (doc_number, doc_id))
    insert_lines(conn, doc_id, uid, appr, False, now)
    conn.execute(
        "INSERT INTO doc_history (doc_id, user_id, user_name, action, comment) VALUES (?,?,?,?,?)",
        (doc_id, uid, u["name"], "기안", ""),
    )
    conn.execute("UPDATE rfqs SET status='pending', partner_id=?, doc_id=? WHERE id=?",
                 (vendor["partner_id"], doc_id, rfq_id))
    audit.log(conn, uid, "doc_submit", "doc", doc_id, f"{doc_number} {title}", company_id=book)
    line = current_line(conn, doc_id)
    create_notification(conn, line["approver_id"], "결재 요청", title, f"/erp_doc/{doc_id}")
    log_activity(conn, uid, "submit", "purchase", rfq_id, rfq["rfq_number"], title)
    conn.commit()
    return RedirectResponse(f"/rfqs/{rfq_id}", status_code=303)


@router.post("/rfqs/{rfq_id}/po")
async def rfq_to_po(request: Request, rfq_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    rfq = _rfq(conn, book, rfq_id)
    if not rfq:
        return JSONResponse({"error": "견적요청을 찾을 수 없습니다."}, status_code=404)
    if rfq["status"] != "pending" or rfq["doc_status"] != "done":
        return JSONResponse({"error": "낙찰 결재가 완료되지 않았습니다."}, status_code=400)
    lines, vendors = _compare(conn, rfq_id)
    vendor = next(v for v in vendors if v["partner_id"] == rfq["partner_id"])
    total = vendor["total"]
    tax = int(total * 0.1)
    po_date = today_kst()
    # 낙찰 품의가 발주 결재를 갈음. 발주는 확정 상태로 생성
    po_number, seq = _next_po_number(conn)
    while True:
        try:
            po_id = conn.execute(
                """INSERT INTO purchase_orders (po_number, partner_id, po_date, delivery_date, status,
                       total_amount, tax_amount, notes, created_by, company_id)
                   VALUES (?,?,?,?, 'confirmed', ?,?,?,?,?)""",
                (po_number, rfq["partner_id"], po_date.isoformat(),
                 (po_date + timedelta(days=vendor["lead_days"])).isoformat(), total, tax,
                 f"견적요청 {rfq['rfq_number']} 낙찰 ({rfq['doc_number']})", u["id"], book),
            ).lastrowid
            break
        except sqlite3.IntegrityError:
            seq += 1
            po_number, _ = _next_po_number(conn, seq)
    for i, (l, p) in enumerate(zip(lines, vendor["prices"]), 1):
        conn.execute(
            "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,?,?,?,?,?)",
            (po_id, i, l["item_id"], l["quantity"], p, l["quantity"] * p),
        )
    conn.execute("UPDATE rfqs SET status='ordered', po_id=? WHERE id=?", (po_id, rfq_id))
    if rfq["pr_id"]:
        conn.execute("UPDATE purchase_requisitions SET status='converted' WHERE id=?", (rfq["pr_id"],))
    log_activity(conn, u["id"], "create", "purchase", po_id, po_number,
                 f"발주서 작성 {po_number} ({vendor['name']}, {total:,}원, {rfq['rfq_number']} 낙찰)")
    audit.log(conn, u["id"], "po_approve", "po", po_id, po_number, company_id=book)
    conn.commit()
    return RedirectResponse(f"/purchase-orders/{po_id}", status_code=303)


@router.post("/rfqs/{rfq_id}/cancel")
async def rfq_cancel(request: Request, rfq_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    rfq = _rfq(conn, u["book"], rfq_id)
    if not rfq:
        return JSONResponse({"error": "견적요청을 찾을 수 없습니다."}, status_code=404)
    if not (rfq["status"] == "open" or (rfq["status"] == "pending" and rfq["doc_status"] == "rejected")):
        return JSONResponse({"error": "취소할 수 없는 상태입니다."}, status_code=400)
    conn.execute("UPDATE rfqs SET status='cancelled' WHERE id=?", (rfq_id,))
    if rfq["pr_id"]:
        conn.execute("UPDATE purchase_requisitions SET status='approved' WHERE id=? AND status='rfq'", (rfq["pr_id"],))
    log_activity(conn, u["id"], "cancel", "purchase", rfq_id, rfq["rfq_number"], f"견적요청 취소 {rfq['rfq_number']}")
    conn.commit()
    return RedirectResponse(f"/rfqs/{rfq_id}", status_code=303)
