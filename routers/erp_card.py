from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core import audit, bankfile, books, invoices, partner
from core.books import require_book
from core.deps import get_db, templates
from core.export import csv_response

router = APIRouter()

STATUSES = ("new", "posted", "skip")
STATUS_LABELS = {"new": "미처리", "posted": "처리", "skip": "제외"}
STATUS_CLASS = {"new": "status-badge status-wait", "posted": "status-badge status-done",
                 "skip": "status-badge status-reject"}
CARD_SORTS = {"date": "approve_date", "merchant": "merchant", "total": "total", "status": "status"}


def _ctx(request, u, **extra):
    return {"request": request, "page_title": "법인카드 사용내역", "user_name": u["name"], **extra}


def _chart(conn, book):
    return books.acct_opts(conn, book)


# 사업자번호로 조회 후 없으면 신규 등록. 코드는 거래처 다음 순번 사용
def _find_merchant(conn, book, uid, merchant, biz_no):
    if biz_no:
        row = conn.execute("SELECT id FROM partners WHERE company_id=? AND biz_no=?", (book, biz_no)).fetchone()
        if row:
            return row["id"]
    code = partner.next_code(conn, book)
    return conn.execute(
        "INSERT INTO partners (company_id, code, name, partner_type, biz_no, created_by) VALUES (?,?,?,'supplier',?,?)",
        (book, code, merchant or "거래처", biz_no, uid),
    ).lastrowid


def _card_rows(conn, book, rows, cmap):
    added = dup = 0
    for t in bankfile.parse_card(rows, cmap):
        biz_no = partner.norm_biz_no(t["merchant_biz_no"]) or "" if t["merchant_biz_no"] else ""
        cur = conn.execute(
            """INSERT OR IGNORE INTO card_txns
                   (company_id, card_no, approve_date, approval_no, merchant, merchant_biz_no, supply_amt, vat, total)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (book, t["card_no"], t["approve_date"], t["approval_no"], t["merchant"], biz_no,
             t["supply_amt"], t["vat"], t["total"]),
        )
        if cur.rowcount:
            added += 1
        else:
            dup += 1
    return added, dup


@router.get("/card-txns/upload", response_class=HTMLResponse)
async def card_upload_form(request: Request, u: dict = Depends(require_book)):
    return templates.TemplateResponse(request=request, name="erp/card_txn_upload.html", context=_ctx(request, u))


@router.post("/card-txns/upload", response_class=HTMLResponse)
async def card_upload(request: Request, file: UploadFile = File(...),
                      u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    data = await file.read()
    try:
        rows = bankfile.read_rows(data, file.filename)
    except Exception:
        return templates.TemplateResponse(request=request, name="erp/card_txn_upload.html", context=_ctx(
            request, u, error="파일을 읽을 수 없습니다. 카드사에서 받은 xlsx 또는 csv 파일인지 확인해 주세요."), status_code=400)

    found = bankfile.find_header(rows, bankfile.CARD_FIELDS, bankfile.CARD_REQUIRED)
    if not found:
        return templates.TemplateResponse(request=request, name="erp/card_txn_upload.html", context=_ctx(
            request, u, error="승인일자/승인번호/이용금액 열을 찾을 수 없습니다. 카드사 이용내역 파일인지 확인해 주세요."), status_code=400)

    header_idx, cmap = found
    added, dup = _card_rows(conn, book, rows[header_idx + 1:], cmap)
    conn.commit()
    return templates.TemplateResponse(request=request, name="erp/card_txn_upload.html", context=_ctx(
        request, u, result={"added": added, "dup": dup}))


@router.get("/card-txns", response_class=HTMLResponse)
async def card_txn_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                        sort: str = "", dir: str = "", export: str = ""):
    book = u["book"]
    qp = request.query_params
    status = qp.get("status", "new")
    if status not in STATUSES and status != "":
        status = "new"

    where, params = ["company_id=?"], [book]
    if status:
        where.append("status=?")
        params.append(status)
    order = CARD_SORTS.get(sort)
    order_sql = f"ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, id DESC" if order \
        else "ORDER BY approve_date DESC, id DESC"
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM card_txns WHERE {' AND '.join(where)} {order_sql}", params).fetchall()]
    for r in rows:
        r["status_label"] = STATUS_LABELS.get(r["status"], r["status"])
        r["status_class"] = STATUS_CLASS.get(r["status"], "")

    if export == "csv":
        csv_rows = [[r["approve_date"], r["approval_no"], r["merchant"], r["supply_amt"], r["vat"], r["total"],
                     r["status_label"]] for r in rows]
        return csv_response(["승인일자", "승인번호", "가맹점", "공급가액", "부가세", "이용금액", "상태"],
                            csv_rows, "card_txns.csv")

    return templates.TemplateResponse(request=request, name="erp/card_txn_list.html", context=_ctx(
        request, u, rows=rows, status=status, chart=_chart(conn, book), partners=books.partner_opts(conn, book),
        nondeduct_reasons=invoices.NONDEDUCT_REASONS, sort=sort, dir=dir))


@router.post("/card-txns/process")
async def card_txn_process(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    book, uid = u["book"], u["id"]
    form = await request.form()
    ids = [int(x) for x in form.getlist("ids") if x.isdigit()]
    if not ids:
        return JSONResponse({"error": "선택된 거래가 없습니다."}, status_code=400)

    card_pid_raw = form.get("card_partner_id", "")
    if not card_pid_raw.isdigit() or not conn.execute(
        "SELECT 1 FROM partners WHERE id=? AND company_id=?", (int(card_pid_raw), book)
    ).fetchone():
        return JSONResponse({"error": "카드사를 선택해 주세요."}, status_code=400)
    card_pid = int(card_pid_raw)

    for tid in ids:
        t = conn.execute("SELECT * FROM card_txns WHERE id=? AND company_id=? AND status='new'", (tid, book)).fetchone()
        if not t:
            conn.rollback()
            return JSONResponse({"error": f"이미 처리되었거나 없는 거래입니다 (id {tid})"}, status_code=400)

        acct = form.get(f"account_code_{tid}", "").strip()
        if not acct or not conn.execute(
            "SELECT 1 FROM accounts WHERE company_id=? AND code=? AND is_active=1", (book, acct)
        ).fetchone():
            conn.rollback()
            return JSONResponse({"error": f"{t['approve_date']} 거래의 비용 계정을 선택해 주세요."}, status_code=400)

        deduct = form.get(f"deduct_{tid}") == "1"
        merchant_pid = _find_merchant(conn, book, uid, t["merchant"], t["merchant_biz_no"])
        slip_date = t["approve_date"][:10]

        try:
            if deduct and t["vat"]:
                inv = {"kind": "매입", "tax_type": "과세", "evidence": "카드", "issue_date": slip_date,
                       "partner_id": merchant_pid, "supply_amt": t["supply_amt"], "vat": t["vat"],
                       "approval_no": t["approval_no"], "is_electronic": 1, "deduct": 1,
                       "source_type": "card", "source_id": tid, "receipt_type": "청구", "remark": ""}
                items = [{"name": t["merchant"] or "법인카드 매입", "supply_amt": t["supply_amt"], "vat": t["vat"]}]
                title = f"매입 카드 ({t['merchant']})"
                lines = invoices.inv_lines(inv, acct, "254", title, card_pid)
                doc_id = books.post(conn, book, uid, slip_date, lines, title, "card", tid)
                inv_id = invoices.add(conn, book, uid, {**inv, "doc_id": doc_id}, items)
                conn.execute("UPDATE card_txns SET status='posted', tax_invoice_id=?, doc_id=? WHERE id=?",
                            (inv_id, doc_id, tid))
            else:
                reason_label = ""
                if t["vat"] and not deduct:
                    reason_raw = form.get(f"nondeduct_reason_{tid}", "")
                    if not reason_raw.isdigit() or int(reason_raw) not in invoices.NONDEDUCT_REASONS:
                        conn.rollback()
                        return JSONResponse(
                            {"error": f"{t['approve_date']} 거래의 불공제 사유를 선택해 주세요."}, status_code=400)
                    reason_label = f" [불공제: {invoices.NONDEDUCT_REASONS[int(reason_raw)]}]"
                title = f"법인카드 매입 ({t['merchant']}){reason_label}"
                lines = [{"code": acct, "debit": t["total"], "credit": 0, "partner_id": merchant_pid, "summary": title},
                         {"code": "254", "debit": 0, "credit": t["total"], "partner_id": card_pid, "summary": title}]
                doc_id = books.post(conn, book, uid, slip_date, lines, title, "card", tid)
                conn.execute("UPDATE card_txns SET status='posted', doc_id=? WHERE id=?", (doc_id, tid))
        except ValueError as e:
            conn.rollback()
            return JSONResponse({"error": f"{t['approve_date']} {e}"}, status_code=400)

        audit.log(conn, uid, "card_post", "card_txn", tid, f"{t['approve_date']} {t['merchant']} {t['total']:,}",
                  company_id=book)

    conn.commit()
    return RedirectResponse("/card-txns", status_code=303)


@router.patch("/card-txns")
async def card_txn_exclude(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("ids") if x.isdigit()]
    status = form.get("status", "")
    if status != "skip" or not ids:
        return JSONResponse({"error": "잘못된 요청입니다."}, status_code=400)
    book = u["book"]
    q = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE card_txns SET status='skip' WHERE company_id=? AND status='new' AND id IN ({q})",
        (book, *ids))
    conn.commit()
    return JSONResponse({"ok": True})
