import json
import os
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core import audit, bankfile, books, credit, partner
from core.books import require_book
from core.deps import get_db, templates
from core.export import csv_response
from core.tz import now_kst

router = APIRouter()

BANK_TMP_DIR = "var/tmp/bank"
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
EXTS = (".xlsx", ".csv")
STATUSES = ("미처리", "처리", "제외")


def _accounts(conn, book):
    return conn.execute(
        "SELECT id, bank, account_no, name, account_code FROM bank_accounts "
        "WHERE company_id=? AND is_active=1 ORDER BY bank, account_no",
        (book,)).fetchall()


def _get_account(conn, book, account_id):
    acct = conn.execute("SELECT * FROM bank_accounts WHERE id=? AND company_id=?", (account_id, book)).fetchone()
    if not acct:
        raise HTTPException(status_code=404)
    return acct


def _ctx(request, u, **extra):
    return {"request": request, "page_title": "은행 거래내역 업로드", "user_name": u["name"], **extra}


def _chart(conn, book):
    return conn.execute(
        "SELECT code, name FROM accounts WHERE company_id=? AND is_active=1 ORDER BY code", (book,)).fetchall()


def _partners(conn, book):
    return conn.execute(
        "SELECT id, name FROM partners WHERE company_id=? AND is_active=1 ORDER BY name", (book,)).fetchall()


# 겹치는 키워드는 긴 쪽 우선
def match_rule(rules, text):
    best = None
    for r in rules:
        kw = r["keyword"]
        if kw and kw in text and (not best or len(kw) > len(best["keyword"])):
            best = r
    return best


def _detect(rows, acct):
    preset = acct["import_preset"]
    if preset:
        fields = {k: [v] for k, v in json.loads(acct["column_map"]).items()} if preset == "generic" \
            else bankfile.PRESETS.get(preset, {})
        found = bankfile.find_header(rows, fields)
        return found, preset if found else None
    for name, fields in bankfile.PRESETS.items():
        found = bankfile.find_header(rows, fields)
        if found:
            return found, name
    return None, None


def _import_rows(conn, book, uid, account_id, rows, cmap):
    existing = {r["hash"] for r in conn.execute(
        "SELECT hash FROM bank_txns WHERE bank_account_id=?", (account_id,))}
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    added = dup = 0
    for t in bankfile.parse(rows, cmap):
        h = bankfile.txn_hash(account_id, t)
        if h in existing:
            dup += 1
            continue
        conn.execute(
            """INSERT INTO bank_txns (company_id, bank_account_id, txn_at, memo, counterparty,
                   amt_in, amt_out, balance, hash, uploaded_by, uploaded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (book, account_id, t["txn_at"], t["memo"], t["party"], t["amt_in"], t["amt_out"], t["balance"],
             h, uid, now),
        )
        existing.add(h)
        added += 1
    return added, dup


@router.get("/bank-txns/upload", response_class=HTMLResponse)
async def bank_upload_form(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    return templates.TemplateResponse(request=request, name="erp/bank_txn_upload.html", context=_ctx(
        request, u, accounts=_accounts(conn, u["book"])))


@router.post("/bank-txns/upload", response_class=HTMLResponse)
async def bank_upload(request: Request, account_id: int = Form(...), file: UploadFile = File(...),
                      u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    acct = _get_account(conn, book, account_id)
    data = await file.read()
    try:
        rows = bankfile.read_rows(data, file.filename)
    except Exception:
        return templates.TemplateResponse(request=request, name="erp/bank_txn_upload.html", context=_ctx(
            request, u, accounts=_accounts(conn, book),
            error="파일을 읽을 수 없습니다. 은행에서 받은 xlsx 또는 csv 파일인지 확인해 주세요."), status_code=400)

    found, preset_name = _detect(rows, acct)
    if not found:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in EXTS:
            ext = ".xlsx"
        token = uuid.uuid4().hex
        os.makedirs(BANK_TMP_DIR, exist_ok=True)
        with open(os.path.join(BANK_TMP_DIR, f"{token}{ext}"), "wb") as f:
            f.write(data)
        max_cols = max((len(r) for r in rows[:20]), default=0)
        return templates.TemplateResponse(request=request, name="erp/bank_txn_upload.html", context=_ctx(
            request, u, mapping={"token": token, "ext": ext, "account_id": account_id,
                                  "rows": rows[:20], "max_cols": max_cols}))

    header_idx, cmap = found
    if not acct["import_preset"]:
        conn.execute("UPDATE bank_accounts SET import_preset=? WHERE id=?", (preset_name, account_id))

    added, dup = _import_rows(conn, book, u["id"], account_id, rows[header_idx + 1:], cmap)
    conn.commit()
    return templates.TemplateResponse(request=request, name="erp/bank_txn_upload.html", context=_ctx(
        request, u, accounts=_accounts(conn, book), result={"added": added, "dup": dup, "account_id": account_id}))


@router.post("/bank-txns/upload/map", response_class=HTMLResponse)
async def bank_upload_map(request: Request, token: str = Form(...), ext: str = Form(...),
                          account_id: int = Form(...), header_row: int = Form(...),
                          date_col: int = Form(...), amt_in_col: int = Form(...), amt_out_col: int = Form(...),
                          memo_col: str = Form(""), party_col: str = Form(""), balance_col: str = Form(""),
                          u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    _get_account(conn, book, account_id)
    if not TOKEN_RE.match(token) or ext not in EXTS:
        raise HTTPException(status_code=400)
    path = os.path.join(BANK_TMP_DIR, f"{token}{ext}")
    if not os.path.exists(path):
        raise HTTPException(status_code=404)

    with open(path, "rb") as f:
        data = f.read()
    rows = bankfile.read_rows(data, f"x{ext}")
    if header_row < 0 or header_row >= len(rows):
        raise HTTPException(status_code=400)
    header = rows[header_row]

    cmap, names = {}, {}
    for field, col in (("date", date_col), ("amt_in", amt_in_col), ("amt_out", amt_out_col)):
        cmap[field] = col
        names[field] = str(header[col]).strip()
    for field, col in (("memo", memo_col), ("party", party_col), ("balance", balance_col)):
        if col != "":
            cmap[field] = int(col)
            names[field] = str(header[int(col)]).strip()

    conn.execute("UPDATE bank_accounts SET import_preset='generic', column_map=? WHERE id=?",
                 (json.dumps(names, ensure_ascii=False), account_id))
    added, dup = _import_rows(conn, book, u["id"], account_id, rows[header_row + 1:], cmap)
    conn.commit()
    os.remove(path)
    return templates.TemplateResponse(request=request, name="erp/bank_txn_upload.html", context=_ctx(
        request, u, accounts=_accounts(conn, book), result={"added": added, "dup": dup, "account_id": account_id}))


BANK_TXN_SORTS = {"date": "txn_at", "party": "counterparty", "in": "amt_in", "out": "amt_out", "status": "status"}


@router.get("/bank-txns", response_class=HTMLResponse)
async def bank_txn_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                         sort: str = "", dir: str = "", export: str = ""):
    book = u["book"]
    accounts = _accounts(conn, book)
    if not accounts:
        return HTMLResponse("<h2>등록된 계좌가 없습니다</h2>", status_code=404)

    qp = request.query_params
    raw_account_id = qp.get("account_id", "")
    account_id = int(raw_account_id) if raw_account_id.isdigit() and \
        any(a["id"] == int(raw_account_id) for a in accounts) else accounts[0]["id"]
    acct = next(a for a in accounts if a["id"] == account_id)

    start, end = qp.get("start", ""), qp.get("end", "")
    status = qp.get("status", "미처리")
    if status not in STATUSES and status != "":
        status = "미처리"

    where, params = ["company_id=?", "bank_account_id=?"], [book, account_id]
    if start:
        where.append("txn_at>=?")
        params.append(start)
    if end:
        where.append("txn_at<=?")
        params.append(end + " 23:59:59")
    if status:
        where.append("status=?")
        params.append(status)
    order = BANK_TXN_SORTS.get(sort)
    order_sql = f"ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, id DESC" if order else "ORDER BY txn_at DESC, id DESC"
    txns = conn.execute(
        f"SELECT * FROM bank_txns WHERE {' AND '.join(where)} {order_sql}", params
    ).fetchall()

    rules = conn.execute("SELECT * FROM txn_rules WHERE company_id=?", (book,)).fetchall()
    partners = _partners(conn, book)
    partner_by_name = {p["name"]: p["id"] for p in partners}
    partner_by_id = {p["id"]: p["name"] for p in partners}
    chart = _chart(conn, book)
    acct_by_code = {a["code"]: a["name"] for a in chart}

    rows = []
    for t in txns:
        m = match_rule(rules, f"{t['memo']} {t['counterparty']}")
        account_code = m["account_code"] if m else ""
        pid = (m["partner_id"] if m else None) or partner_by_name.get(t["counterparty"])
        settle_link = None
        if t["status"] == "미처리" and pid:
            if t["amt_in"] and credit.open_items(conn, book, "110", pid).get(pid, {"items": []})["items"]:
                settle_link = f"/settlements/new?kind=수금&partner_id={pid}&amount={t['amt_in']}&bank_txn_id={t['id']}"
            elif t["amt_out"] and credit.open_items(conn, book, "251", pid).get(pid, {"items": []})["items"]:
                settle_link = f"/settlements/new?kind=지급&partner_id={pid}&amount={t['amt_out']}&bank_txn_id={t['id']}"
        rows.append({"t": t, "account_code": account_code, "partner_id": pid, "settle_link": settle_link})

    if export == "csv":
        csv_rows = [[
            r["t"]["txn_at"], r["t"]["memo"], r["t"]["counterparty"],
            r["t"]["amt_in"] or 0, r["t"]["amt_out"] or 0,
            acct_by_code.get(r["account_code"], ""), partner_by_id.get(r["partner_id"], ""),
            r["t"]["status"],
        ] for r in rows]
        return csv_response(["일자", "적요", "거래상대", "입금", "출금", "계정", "거래처", "상태"], csv_rows, "bank_txns.csv")

    last = conn.execute(
        "SELECT * FROM bank_txns WHERE company_id=? AND bank_account_id=? ORDER BY txn_at DESC, id DESC LIMIT 1",
        (book, account_id)
    ).fetchone()
    recon = None
    if last and last["balance"] is not None:
        book_bal = conn.execute(
            """SELECT COALESCE(SUM(sl.debit),0) - COALESCE(SUM(sl.credit),0) FROM slip_lines sl
               JOIN erp_docs d ON sl.doc_id=d.id
               WHERE d.company_id=? AND d.status='done' AND sl.account_code=? AND d.slip_date<=?""",
            (book, acct["account_code"], last["txn_at"][:10])
        ).fetchone()[0]
        recon = {"bank_balance": last["balance"], "book_balance": book_bal, "diff": last["balance"] - book_bal}
    shared = conn.execute(
        "SELECT COUNT(*) FROM bank_accounts WHERE company_id=? AND account_code=? AND is_active=1",
        (book, acct["account_code"])
    ).fetchone()[0] > 1

    return templates.TemplateResponse(request=request, name="erp/bank_txn_list.html", context={
        "request": request, "page_title": "은행 거래내역", "user_name": u["name"],
        "accounts": accounts, "account_id": account_id, "acct": acct,
        "start": start, "end": end, "status": status, "rows": rows,
        "chart": chart, "partners": partners,
        "recon": recon, "shared": shared, "sort": sort, "dir": dir,
    })


@router.post("/bank-txns/slips")
async def bank_txn_slips(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    book, uid = u["book"], u["id"]
    form = await request.form()
    ids = [int(x) for x in form.getlist("ids") if x.isdigit()]
    if not ids:
        return JSONResponse({"error": "선택된 거래가 없습니다."}, status_code=400)

    rules = conn.execute("SELECT * FROM txn_rules WHERE company_id=?", (book,)).fetchall()
    bank_account_id = None
    for tid in ids:
        txn = conn.execute(
            "SELECT * FROM bank_txns WHERE id=? AND company_id=? AND status='미처리'", (tid, book)
        ).fetchone()
        if not txn:
            conn.rollback()
            return JSONResponse({"error": f"이미 처리되었거나 없는 거래입니다 (id {tid})"}, status_code=400)
        bank_account_id = txn["bank_account_id"]
        bank_code = conn.execute(
            "SELECT account_code FROM bank_accounts WHERE id=?", (bank_account_id,)
        ).fetchone()["account_code"]

        code = form.get(f"account_code_{tid}", "").strip()
        pid_raw = form.get(f"partner_id_{tid}", "")
        pid = int(pid_raw) if pid_raw.isdigit() else None
        if not code:
            conn.rollback()
            return JSONResponse({"error": f"{txn['txn_at']} 거래에 계정을 선택해 주세요."}, status_code=400)

        amt = txn["amt_in"] or txn["amt_out"]
        title = txn["counterparty"] or txn["memo"] or "은행거래"
        if txn["amt_in"]:
            lines = [{"code": bank_code, "debit": amt, "credit": 0},
                     {"code": code, "debit": 0, "credit": amt, "partner_id": pid}]
        else:
            lines = [{"code": code, "debit": amt, "credit": 0, "partner_id": pid},
                     {"code": bank_code, "debit": 0, "credit": amt}]
        try:
            doc_id = books.post(conn, book, uid, txn["txn_at"][:10], lines, title, "bank_txn", tid)
        except ValueError as e:
            conn.rollback()
            return JSONResponse({"error": f"{txn['txn_at']} {e}"}, status_code=400)

        conn.execute("UPDATE bank_txns SET status='처리', doc_id=? WHERE id=?", (doc_id, tid))

        m = match_rule(rules, f"{txn['memo']} {txn['counterparty']}")
        if m:
            conn.execute("UPDATE txn_rules SET hit_cnt=hit_cnt+1 WHERE id=?", (m["id"],))
        if form.get(f"save_rule_{tid}") == "1":
            keyword = txn["counterparty"] or txn["memo"]
            if keyword and not conn.execute(
                "SELECT 1 FROM txn_rules WHERE company_id=? AND keyword=?", (book, keyword)
            ).fetchone():
                conn.execute(
                    "INSERT INTO txn_rules (company_id, keyword, account_code, partner_id, created_by) "
                    "VALUES (?,?,?,?,?)",
                    (book, keyword, code, pid, uid))

        audit.log(conn, uid, "bank_post", "bank_txn", tid, f"{txn['txn_at']} {title} {amt:,}", company_id=book)

    conn.commit()
    return RedirectResponse(f"/bank-txns?account_id={bank_account_id}", status_code=303)


@router.patch("/bank-txns")
async def bank_txn_exclude(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("ids") if x.isdigit()]
    status = form.get("status", "")
    if status != "제외" or not ids:
        return JSONResponse({"error": "잘못된 요청입니다."}, status_code=400)
    book = u["book"]
    q = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE bank_txns SET status='제외' WHERE company_id=? AND status='미처리' AND id IN ({q})",
        (book, *ids))
    conn.commit()
    return JSONResponse({"ok": True})


RULE_SORTS = {"keyword": "r.keyword", "account": "r.account_code", "partner": "partner_name", "hits": "r.hit_cnt"}


@router.get("/bank-txns/rules", response_class=HTMLResponse)
async def txn_rule_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                         sort: str = "", dir: str = "", export: str = ""):
    book = u["book"]
    order = RULE_SORTS.get(sort)
    order_sql = f"ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, r.keyword" if order else "ORDER BY r.hit_cnt DESC, r.keyword"
    rules = conn.execute(
        f"""SELECT r.*, a.name AS account_name, p.name AS partner_name FROM txn_rules r
           LEFT JOIN accounts a ON a.company_id=r.company_id AND a.code=r.account_code
           LEFT JOIN partners p ON p.id=r.partner_id
           WHERE r.company_id=? {order_sql}""", (book,)
    ).fetchall()

    if export == "csv":
        csv_rows = [[r["keyword"], f"{r['account_code']} {r['account_name'] or ''}".strip(),
                     r["partner_name"] or "", r["hit_cnt"]] for r in rules]
        return csv_response(["키워드", "계정", "거래처", "적용 횟수"], csv_rows, "bank_rules.csv")

    return templates.TemplateResponse(request=request, name="erp/bank_rule_list.html", context={
        "request": request, "page_title": "은행 거래 규칙", "user_name": u["name"],
        "rules": rules, "chart": _chart(conn, book), "partners": _partners(conn, book),
        "can_edit": partner.can_edit(u), "sort": sort, "dir": dir,
    })


@router.patch("/bank-txns/rules/{rule_id}")
async def txn_rule_update(rule_id: int, request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    if not conn.execute("SELECT 1 FROM txn_rules WHERE id=? AND company_id=?", (rule_id, book)).fetchone():
        raise HTTPException(status_code=404)
    form = await request.form()
    code = form.get("account_code", "").strip()
    pid_raw = form.get("partner_id", "")
    if not code or not conn.execute(
        "SELECT 1 FROM accounts WHERE company_id=? AND code=? AND is_active=1", (book, code)
    ).fetchone():
        return JSONResponse({"error": "계정을 확인해 주세요."}, status_code=400)
    conn.execute("UPDATE txn_rules SET account_code=?, partner_id=? WHERE id=?",
                 (code, int(pid_raw) if pid_raw.isdigit() else None, rule_id))
    conn.commit()
    return JSONResponse({"ok": True})


@router.delete("/bank-txns/rules/{rule_id}")
async def txn_rule_delete(rule_id: int, u: dict = Depends(partner.require_editor), conn=Depends(get_db)):
    book = u["book"]
    if not conn.execute("SELECT 1 FROM txn_rules WHERE id=? AND company_id=?", (rule_id, book)).fetchone():
        raise HTTPException(status_code=404)
    conn.execute("DELETE FROM txn_rules WHERE id=?", (rule_id,))
    conn.commit()
    return JSONResponse({"ok": True})
