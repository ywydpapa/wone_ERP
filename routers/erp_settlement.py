from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core import credit, partner, settle
from core.books import require_book
from core.deps import get_db, templates
from core.export import csv_response
from core.tz import now_kst

router = APIRouter()

PER_PAGE = 30
WHT_LABELS = {"없음": "없음", "사업소득": "사업소득 3.3%", "기타소득": "기타소득 8.8%"}
SETTLE_SORTS = {"date": "s.settle_date", "partner": "p.name", "amount": "s.amount", "status": "s.canceled_at"}


def _int(v):
    v = str(v).replace(",", "").strip()
    if not v.lstrip("-").isdigit():
        raise ValueError
    return int(v)


def _active_partners(conn, book):
    return conn.execute("SELECT id, name FROM partners WHERE company_id=? AND is_active=1 ORDER BY name",
                        (book,)).fetchall()


@router.get("/settlements", response_class=HTMLResponse)
async def settlement_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                           sort: str = "", dir: str = "", export: str = ""):
    book = u["book"]
    qp = request.query_params
    today = now_kst().strftime("%Y-%m-%d")
    start = qp.get("start") or f"{today[:8]}01"
    end = qp.get("end") or today
    kind = qp.get("kind", "")
    partner_id = qp.get("partner_id", "")
    status = qp.get("status", "")
    page = qp.get("page", "1")
    page = int(page) if page.isdigit() else 1

    where = ["s.company_id=?", "s.settle_date BETWEEN ? AND ?"]
    params = [book, start, end]
    if kind in ("수금", "지급"):
        where.append("s.kind=?")
        params.append(kind)
    if partner_id.isdigit():
        where.append("s.partner_id=?")
        params.append(int(partner_id))
    if status == "정상":
        where.append("s.canceled_at IS NULL")
    elif status == "취소":
        where.append("s.canceled_at IS NOT NULL")
    where_sql = " AND ".join(where)

    order = SETTLE_SORTS.get(sort)
    order_sql = f"ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, s.id DESC" if order else "ORDER BY s.settle_date DESC, s.id DESC"

    if export == "csv":
        all_rows = conn.execute(
            f"""SELECT s.*, p.name AS partner_name, d.slip_no
                FROM settlements s JOIN partners p ON p.id=s.partner_id
                LEFT JOIN erp_docs d ON d.id=s.doc_id
                WHERE {where_sql} {order_sql}""",
            params,
        ).fetchall()
        csv_rows = [[r["settle_date"], r["kind"], r["partner_name"], r["amount"], r["wht_amt"] or 0,
                     r["method"], r["slip_no"] or "", "취소" if r["canceled_at"] else "정상"] for r in all_rows]
        return csv_response(["일자", "구분", "거래처", "금액", "원천세", "결제방법", "전표번호", "상태"],
                            csv_rows, "settlements.csv")

    total = conn.execute(f"SELECT COUNT(*) FROM settlements s WHERE {where_sql}", params).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    rows = conn.execute(
        f"""SELECT s.*, p.name AS partner_name, d.slip_no
            FROM settlements s JOIN partners p ON p.id=s.partner_id
            LEFT JOIN erp_docs d ON d.id=s.doc_id
            WHERE {where_sql} {order_sql}
            LIMIT ? OFFSET ?""",
        params + [PER_PAGE, (page - 1) * PER_PAGE],
    ).fetchall()

    return templates.TemplateResponse(request=request, name="erp/settlement_list.html", context={
        "request": request, "page_title": "수금/지급", "user_name": u["name"],
        "rows": rows, "start": start, "end": end, "kind": kind, "partner_id": partner_id, "status": status,
        "partners": _active_partners(conn, book),
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/settlements?start={start}&end={end}&kind={kind}&partner_id={partner_id}&status={status}&sort={sort}&dir={dir}",
        "sort": sort, "dir": dir,
    })


@router.get("/settlements/new", response_class=HTMLResponse)
async def settlement_new(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    qp = request.query_params
    kind = qp.get("kind") if qp.get("kind") in ("수금", "지급") else "수금"
    pid = qp.get("partner_id", "")
    doc_id = qp.get("doc_id", "")
    amount = qp.get("amount", "")
    bank_txn_id = qp.get("bank_txn_id", "")

    partner_row = None
    items = []
    advance_bal = 0
    if pid.isdigit():
        partner_row = conn.execute("SELECT id, name FROM partners WHERE id=? AND company_id=?",
                                   (int(pid), book)).fetchone()
        if partner_row:
            info = credit.open_items(conn, book, settle.ACCT[kind], partner_row["id"]).get(
                partner_row["id"], {"items": []})
            items = info["items"]
            advance_bal = settle.advance_balance(conn, book, kind, partner_row["id"])

    txn = None
    settle_date = now_kst().strftime("%Y-%m-%d")
    method, bank_account_id = "", ""
    if bank_txn_id.isdigit():
        txn = conn.execute("SELECT * FROM bank_txns WHERE id=? AND company_id=? AND status='미처리'",
                           (int(bank_txn_id), book)).fetchone()
        if not txn:
            return HTMLResponse("<h2>은행 거래를 찾을 수 없습니다</h2>", status_code=404)
        settle_date = txn["txn_at"][:10]
        method = "보통예금"
        bank_account_id = str(txn["bank_account_id"])
        amount = str(txn["amt_in"] if kind == "수금" else txn["amt_out"])

    accts = conn.execute("SELECT id, bank, account_no, name FROM bank_accounts WHERE company_id=? AND is_active=1 "
                         "ORDER BY bank, account_no", (book,)).fetchall()
    return templates.TemplateResponse(request=request, name="erp/settlement_form.html", context={
        "request": request, "page_title": f"{kind} 등록", "user_name": u["name"],
        "kind": kind, "partner": partner_row, "partners": _active_partners(conn, book),
        "items": items, "doc_id": doc_id, "amount": amount, "settle_date": settle_date,
        "method": method, "bank_account_id": bank_account_id, "bank_accounts": accts,
        "advance_balance": advance_bal, "bank_txn_id": bank_txn_id, "wht_labels": WHT_LABELS,
    })


@router.post("/settlements")
async def settlement_create(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    book, uid = u["book"], u["id"]
    form = await request.form()
    kind = form.get("kind", "")
    if kind not in ("수금", "지급"):
        return JSONResponse({"error": "구분을 선택해 주세요."}, status_code=400)

    try:
        pid = _int(form.get("partner_id", ""))
        amount = _int(form.get("amount"))
        bank_account_id = _int(form["bank_account_id"]) if form.get("bank_account_id") else None
        bank_txn_id = _int(form["bank_txn_id"]) if form.get("bank_txn_id") else None
        items = [(int(k[len("alloc_"):]), _int(v)) for k, v in form.multi_items()
                 if k.startswith("alloc_") and v]
    except ValueError:
        return JSONResponse({"error": "금액 형식이 잘못되었습니다."}, status_code=400)
    try:
        date.fromisoformat(form.get("settle_date", ""))
    except ValueError:
        return JSONResponse({"error": "일자를 확인해 주세요."}, status_code=400)

    f = {
        "kind": kind, "settle_date": form.get("settle_date", ""), "partner_id": pid, "amount": amount,
        "method": form.get("method", ""), "bank_account_id": bank_account_id,
        "wht_type": form.get("wht_type", "없음") if kind == "지급" else "없음",
        "memo": form.get("memo", "").strip(), "items": items,
        "advance": form.get("advance") == "1", "bank_txn_id": bank_txn_id,
    }
    try:
        sid = settle.create(conn, book, uid, f)
    except LookupError:
        return JSONResponse({"error": "거래처 또는 전표를 찾을 수 없습니다."}, status_code=404)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return RedirectResponse(f"/settlements/{sid}", status_code=303)


@router.get("/settlements/{sid}", response_class=HTMLResponse)
async def settlement_detail(request: Request, sid: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    s = conn.execute(
        """SELECT s.*, p.name AS partner_name, cu.name AS created_name,
                  d.slip_no AS doc_slip_no, cd.slip_no AS cancel_slip_no,
                  ba.bank, ba.account_no, ba.name AS bank_name
           FROM settlements s
           JOIN partners p ON p.id=s.partner_id
           LEFT JOIN users cu ON cu.id=s.created_by
           LEFT JOIN erp_docs d ON d.id=s.doc_id
           LEFT JOIN erp_docs cd ON cd.id=s.cancel_doc_id
           LEFT JOIN bank_accounts ba ON ba.id=s.bank_account_id
           WHERE s.id=? AND s.company_id=?""",
        (sid, book),
    ).fetchone()
    if not s:
        return HTMLResponse("<h2>수금/지급 내역을 찾을 수 없습니다</h2>", status_code=404)

    items = conn.execute(
        """SELECT si.amount, d.slip_no, d.id AS doc_id, d.title
           FROM settlement_items si JOIN erp_docs d ON d.id=si.charge_doc_id
           WHERE si.settlement_id=?""",
        (sid,),
    ).fetchall()

    return templates.TemplateResponse(request=request, name="erp/settlement_detail.html", context={
        "request": request, "page_title": "수금/지급 상세", "user_name": u["name"],
        "s": s, "items": items, "can_cancel": partner.can_edit(u),
    })


@router.delete("/settlements/{sid}")
async def settlement_cancel(sid: int, u: dict = Depends(partner.require_editor), conn=Depends(get_db)):
    try:
        settle.cancel(conn, u["book"], u["id"], sid)
    except LookupError:
        return JSONResponse({"error": "수금/지급 내역을 찾을 수 없습니다."}, status_code=404)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return JSONResponse({"ok": True})
