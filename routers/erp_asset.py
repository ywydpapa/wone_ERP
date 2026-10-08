from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core import assets, books, stock
from core.auth import verify_pw
from core.books import require_book
from core.deps import get_db, templates
from core.erp_log import log_activity
from core.tz import now_kst, today_kst

router = APIRouter()

# 대손충당금 설정 대상 채권
RECV_CODES = ("110", "111")
ALLOW_CODE = "131"
BAD_CODE = "836"
STOCK_CODE = "120"
COGS_CODE = "451"


def _writer(u):
    return u["role"] in ("client", "platform_staff")


def _int(v, default=0):
    v = str(v or "").replace(",", "").strip()
    return int(v) if v.lstrip("-").isdigit() else default


def _bal(conn, book, codes, date_to):
    q = ",".join("?" * len(codes))
    return conn.execute(
        f"""SELECT COALESCE(SUM(sl.debit - sl.credit), 0) FROM slip_lines sl JOIN erp_docs d ON sl.doc_id=d.id
            WHERE d.company_id=? AND d.status='done' AND d.slip_date<=? AND sl.account_code IN ({q})""",
        (book, date_to, *codes),
    ).fetchone()[0]


def _closing_doc(conn, book, year):
    return conn.execute(
        """SELECT id, slip_no FROM erp_docs WHERE company_id=? AND source_type='closing' AND source_id=? AND status='done'
           AND id NOT IN (SELECT reversal_of FROM erp_docs WHERE reversal_of IS NOT NULL)""",
        (book, year),
    ).fetchone()


def _fiscal_closed(conn, book, year):
    return bool(conn.execute(
        "SELECT 1 FROM fiscal_closings WHERE company_id=? AND year=? AND status='closed'", (book, year)
    ).fetchone())


def _year(request):
    y = request.query_params.get("year", "")
    return int(y) if y.isdigit() and 2000 <= int(y) <= 2100 else today_kst().year


def _asset_accounts(conn, book):
    q = ",".join("?" * len(assets.ACCUM))
    return conn.execute(
        f"SELECT code, name FROM accounts WHERE company_id=? AND code IN ({q}) ORDER BY code", (book, *assets.ACCUM)
    ).fetchall()


@router.get("/fa", response_class=HTMLResponse)
async def fa_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    year = _year(request)
    status = request.query_params.get("status", "active")
    sql = """SELECT f.*, a.name AS account_name FROM fixed_assets f
             LEFT JOIN accounts a ON a.company_id=f.company_id AND a.code=f.account_code
             WHERE f.company_id=?"""
    args = [u["book"]]
    if status in ("active", "disposed"):
        sql += " AND f.status=?"
        args.append(status)
    rows = []
    tot = {"cost": 0, "open": 0, "cur": 0, "end": 0, "left": 0}
    for f in conn.execute(sql + " ORDER BY f.account_code, f.code", args).fetchall():
        d = assets.depr(conn, f, year)
        r = dict(f, cur=d["amount"], accum=d["accum"], end=d["accum"] + d["amount"], posted=d["posted"], error=d["error"])
        r["left"] = f["acq_cost"] - r["end"]
        rows.append(r)
        tot["cost"] += f["acq_cost"]
        tot["open"] += r["accum"]
        tot["cur"] += r["cur"]
        tot["end"] += r["end"]
        tot["left"] += r["left"]
    return templates.TemplateResponse(request=request, name="erp/fa_asset_list.html", context={
        "request": request, "page_title": "고정자산 대장", "rows": rows, "tot": tot,
        "year": year, "status": status, "can_write": _writer(u), "saved": request.query_params.get("saved") == "1",
    })


def _asset_form(request, conn, u, asset):
    return templates.TemplateResponse(request=request, name="erp/fa_asset_form.html", context={
        "request": request, "page_title": "고정자산 수정" if asset else "고정자산 등록",
        "a": asset or {}, "accounts": _asset_accounts(conn, u["book"]), "methods": assets.METHODS,
        "locked": bool(asset and conn.execute("SELECT 1 FROM fa_depr WHERE asset_id=?", (asset["id"],)).fetchone()),
    })


@router.get("/fa/new", response_class=HTMLResponse)
async def fa_new(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return RedirectResponse("/fa", status_code=303)
    return _asset_form(request, conn, u, None)


@router.get("/fa/{fa_id}", response_class=HTMLResponse)
async def fa_edit(request: Request, fa_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    a = conn.execute("SELECT * FROM fixed_assets WHERE id=? AND company_id=?", (fa_id, u["book"])).fetchone()
    if not a:
        return HTMLResponse("<h2>자산을 찾을 수 없습니다</h2>", status_code=404)
    if not _writer(u):
        return RedirectResponse("/fa", status_code=303)
    return _asset_form(request, conn, u, dict(a))


def _valid_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return True


async def _read_asset(request, conn, book):
    f = await request.form()
    a = {
        "name": f.get("name", "").strip(), "account_code": f.get("account_code", ""),
        "acq_date": f.get("acq_date", ""), "acq_cost": _int(f.get("acq_cost")),
        "life_years": _int(f.get("life_years")), "method": f.get("method", "정액법"),
        "open_accum": _int(f.get("open_accum")), "open_year": _int(f.get("open_year")),
        "dept": f.get("dept", "").strip(), "status": f.get("status", "active"),
        "disposed_date": f.get("disposed_date", "") or None, "code": f.get("code", "").strip(),
    }
    if not a["name"]:
        return a, "자산명을 입력해 주세요."
    if a["account_code"] not in assets.ACCUM or not conn.execute(
        "SELECT 1 FROM accounts WHERE company_id=? AND code=?", (book, a["account_code"])
    ).fetchone():
        return a, "자산 계정을 선택해 주세요."
    if not _valid_date(a["acq_date"]):
        return a, "취득일을 확인해 주세요."
    if a["acq_cost"] <= 0:
        return a, "취득가액을 입력해 주세요."
    if a["method"] not in assets.METHODS:
        return a, "상각방법을 선택해 주세요."
    if a["method"] == "정률법" and a["life_years"] not in assets.DB_RATES:
        return a, "정률법 내용연수는 2~20년입니다."
    if not 2 <= a["life_years"] <= 60:
        return a, "내용연수는 2~60년입니다."
    acq_y = int(a["acq_date"][:4])
    if a["open_accum"] < 0 or a["open_accum"] >= a["acq_cost"]:
        return a, "기초 상각누계액을 확인해 주세요."
    if a["open_accum"] and a["open_year"] < acq_y:
        return a, "기초 상각누계액 기준연도를 확인해 주세요."
    if not a["open_accum"]:
        a["open_year"] = acq_y - 1
    if a["status"] not in ("active", "disposed"):
        return a, "상태를 확인해 주세요."
    if a["status"] == "disposed" and not (a["disposed_date"] and _valid_date(a["disposed_date"])):
        return a, "처분일을 입력해 주세요."
    if a["status"] == "active":
        a["disposed_date"] = None
    return a, ""


@router.post("/fa")
async def fa_create(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    a, err = await _read_asset(request, conn, book)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    # 더존 기준 5자리 자동채번
    if not a["code"]:
        last = conn.execute(
            "SELECT MAX(CAST(code AS INTEGER)) FROM fixed_assets WHERE company_id=? AND code GLOB '[0-9]*'", (book,)
        ).fetchone()[0]
        a["code"] = f"{(last or 0) + 1:05d}"
    if conn.execute("SELECT 1 FROM fixed_assets WHERE company_id=? AND code=?", (book, a["code"])).fetchone():
        return JSONResponse({"error": "이미 사용 중인 자산코드입니다."}, status_code=400)
    fa_id = conn.execute(
        """INSERT INTO fixed_assets (company_id, code, name, account_code, acq_date, acq_cost, life_years, method,
               open_accum, open_year, dept, status, disposed_date, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (book, a["code"], a["name"], a["account_code"], a["acq_date"], a["acq_cost"], a["life_years"], a["method"],
         a["open_accum"], a["open_year"], a["dept"], a["status"], a["disposed_date"], u["id"]),
    ).lastrowid
    log_activity(conn, u["id"], "create", "fixed_asset", fa_id, a["code"], f"고정자산 등록 {a['name']}")
    conn.commit()
    return RedirectResponse("/fa?saved=1", status_code=303)


@router.post("/fa/{fa_id}")
async def fa_update(request: Request, fa_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    old = conn.execute("SELECT * FROM fixed_assets WHERE id=? AND company_id=?", (fa_id, book)).fetchone()
    if not old:
        return JSONResponse({"error": "자산을 찾을 수 없습니다."}, status_code=404)
    a, err = await _read_asset(request, conn, book)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    # 상각 이력이 있으면 금액 기준 항목 변경 불가
    if conn.execute("SELECT 1 FROM fa_depr WHERE asset_id=?", (fa_id,)).fetchone():
        for k in ("account_code", "acq_date", "acq_cost", "life_years", "method", "open_accum", "open_year"):
            a[k] = old[k]
    conn.execute(
        """UPDATE fixed_assets SET name=?, account_code=?, acq_date=?, acq_cost=?, life_years=?, method=?,
               open_accum=?, open_year=?, dept=?, status=?, disposed_date=? WHERE id=?""",
        (a["name"], a["account_code"], a["acq_date"], a["acq_cost"], a["life_years"], a["method"],
         a["open_accum"], a["open_year"], a["dept"], a["status"], a["disposed_date"], fa_id),
    )
    log_activity(conn, u["id"], "update", "fixed_asset", fa_id, old["code"], f"고정자산 수정 {a['name']}")
    conn.commit()
    return RedirectResponse("/fa?saved=1", status_code=303)


@router.delete("/fa/{fa_id}")
async def fa_delete(fa_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    a = conn.execute("SELECT code, name FROM fixed_assets WHERE id=? AND company_id=?", (fa_id, u["book"])).fetchone()
    if not a:
        return JSONResponse({"error": "자산을 찾을 수 없습니다."}, status_code=404)
    if conn.execute("SELECT 1 FROM fa_depr WHERE asset_id=?", (fa_id,)).fetchone():
        return JSONResponse({"error": "감가상각이 반영된 자산은 삭제할 수 없습니다. 처분으로 처리해 주세요."}, status_code=400)
    conn.execute("DELETE FROM fixed_assets WHERE id=?", (fa_id,))
    log_activity(conn, u["id"], "delete", "fixed_asset", fa_id, a["code"], f"고정자산 삭제 {a['name']}")
    conn.commit()
    return JSONResponse({"ok": True})


def _year_end(conn, book, year, rate, end_stock):
    date_to = f"{year}-12-31"
    rows = []
    for f in conn.execute(
        """SELECT f.*, a.name AS account_name FROM fixed_assets f
           LEFT JOIN accounts a ON a.company_id=f.company_id AND a.code=f.account_code
           WHERE f.company_id=? AND f.acq_date<=? AND (f.disposed_date IS NULL OR f.disposed_date>=?)
           ORDER BY f.account_code, f.code""",
        (book, date_to, f"{year}-01-01"),
    ).fetchall():
        d = assets.depr(conn, f, year)
        if d["amount"] or d["error"]:
            rows.append(dict(f, amount=d["amount"], error=d["error"]))
    recv = _bal(conn, book, RECV_CODES, date_to)
    allow = -_bal(conn, book, (ALLOW_CODE,), date_to)
    stock_bal = _bal(conn, book, (STOCK_CODE,), date_to)
    bad = max(0, recv * rate // 1000 - allow)
    return {
        "assets": rows, "depr": sum(r["amount"] for r in rows if not r["error"]),
        "recv": recv, "allow": allow, "bad": bad,
        "stock": stock_bal, "end_stock": end_stock,
        "cogs": stock_bal - end_stock if end_stock is not None else 0,
    }


def _rate(v):
    # 설정률은 천분율 정수로 처리. 1.5% -> 15
    try:
        r = round(float(str(v).strip() or "1") * 10)
    except ValueError:
        return None
    return r if 0 <= r <= 1000 else None


@router.get("/fi/year-end", response_class=HTMLResponse)
async def year_end(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    year = _year(request)
    qp = request.query_params
    rate = _rate(qp.get("rate", "1")) or 0
    if "end_stock" in qp:
        end_stock = _int(qp["end_stock"], None) if qp["end_stock"].strip() else None
    else:
        end_stock = sum(r["amt"] for r in stock.valuation(conn, u["book"], f"{year}-12-31"))
    doc = _closing_doc(conn, u["book"], year)
    return templates.TemplateResponse(request=request, name="erp/fi_year_end.html", context={
        "request": request, "page_title": "결산자료입력", "year": year,
        "rate": qp.get("rate", "1"), "data": _year_end(conn, u["book"], year, rate, end_stock),
        "doc": doc, "closed": books.period_closed(conn, u["book"], f"{year}-12-31"),
        "can_write": _writer(u), "saved": qp.get("saved") == "1",
    })


@router.post("/fi/year-end")
async def year_end_post(year: int = Form(...), rate: str = Form("1"), end_stock: str = Form(""),
                        u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    r = _rate(rate)
    if r is None:
        return JSONResponse({"error": "대손 설정률을 확인해 주세요."}, status_code=400)
    if _closing_doc(conn, book, year):
        return JSONResponse({"error": "이미 결산분개가 있습니다. 삭제 후 다시 추가해 주세요."}, status_code=400)
    d = _year_end(conn, book, year, r, _int(end_stock) if end_stock.strip() else None)
    lines = []
    if d["depr"]:
        lines.append({"code": assets.DEPR_CODE, "debit": d["depr"], "credit": 0, "summary": f"{year}년 감가상각비"})
        by_acc = {}
        for a in d["assets"]:
            if not a["error"]:
                code = assets.ACCUM[a["account_code"]]
                by_acc[code] = by_acc.get(code, 0) + a["amount"]
        for code, amt in sorted(by_acc.items()):
            lines.append({"code": code, "debit": 0, "credit": amt, "summary": f"{year}년 감가상각비"})
    if d["bad"]:
        lines.append({"code": BAD_CODE, "debit": d["bad"], "credit": 0, "summary": "대손충당금 설정"})
        lines.append({"code": ALLOW_CODE, "debit": 0, "credit": d["bad"], "summary": "대손충당금 설정"})
    if d["cogs"] > 0:
        lines.append({"code": COGS_CODE, "debit": d["cogs"], "credit": 0, "summary": "상품매출원가 대체"})
        lines.append({"code": STOCK_CODE, "debit": 0, "credit": d["cogs"], "summary": "상품매출원가 대체"})
    elif d["cogs"] < 0:
        lines.append({"code": STOCK_CODE, "debit": -d["cogs"], "credit": 0, "summary": "기말상품 대체"})
        lines.append({"code": COGS_CODE, "debit": 0, "credit": -d["cogs"], "summary": "기말상품 대체"})
    if not lines:
        return JSONResponse({"error": "반영할 결산 금액이 없습니다."}, status_code=400)
    try:
        doc_id = books.post(conn, book, u["id"], f"{year}-12-31", lines, f"{year}년 결산분개", "closing", year)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    for a in d["assets"]:
        if a["amount"] and not a["error"]:
            conn.execute("INSERT INTO fa_depr (company_id, asset_id, year, amount, doc_id) VALUES (?,?,?,?,?)",
                         (book, a["id"], year, a["amount"], doc_id))
    log_activity(conn, u["id"], "create", "slip", doc_id, str(year), f"{year}년 결산분개 추가")
    conn.commit()
    return RedirectResponse(f"/fi/year-end?year={year}&saved=1", status_code=303)


@router.delete("/fi/year-end/{year}")
async def year_end_delete(year: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    doc = _closing_doc(conn, book, year)
    if not doc:
        return JSONResponse({"error": "결산분개가 없습니다."}, status_code=404)
    if books.period_closed(conn, book, f"{year}-12-31"):
        return JSONResponse({"error": "마감된 회계기간입니다."}, status_code=400)
    # 더존 자동결산 기준. 결산분개는 삭제 후 재생성
    conn.execute("DELETE FROM fa_depr WHERE doc_id=?", (doc["id"],))
    conn.execute("DELETE FROM slip_lines WHERE doc_id=?", (doc["id"],))
    conn.execute("DELETE FROM erp_docs WHERE id=?", (doc["id"],))
    log_activity(conn, u["id"], "delete", "slip", doc["id"], doc["slip_no"], f"{year}년 결산분개 삭제")
    conn.commit()
    return JSONResponse({"ok": True})


@router.get("/fi/fiscal", response_class=HTMLResponse)
async def fiscal_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    first = conn.execute(
        "SELECT MIN(substr(slip_date, 1, 4)) FROM erp_docs WHERE company_id=? AND status='done' AND slip_date != ''", (book,)
    ).fetchone()[0]
    this = today_kst().year
    rows = []
    for y in range(this, int(first or this) - 1, -1):
        c = conn.execute(
            """SELECT f.*, cu.name AS closed_name, ru.name AS reopened_name FROM fiscal_closings f
               LEFT JOIN users cu ON cu.id=f.closed_by LEFT JOIN users ru ON ru.id=f.reopened_by
               WHERE f.company_id=? AND f.year=?""", (book, y)
        ).fetchone()
        doc = _closing_doc(conn, book, y)
        rows.append({"year": y, "c": dict(c) if c else None, "closed": bool(c and c["status"] == "closed"),
                     "doc": dict(doc) if doc else None, "ended": y < this})
    return templates.TemplateResponse(request=request, name="erp/fi_fiscal.html", context={
        "request": request, "page_title": "회기 마감", "rows": rows, "can_write": _writer(u),
    })


@router.post("/fi/fiscal")
async def fiscal_close(year: int = Form(...), u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    if year >= today_kst().year:
        return JSONResponse({"error": "회계연도가 끝난 후 마감할 수 있습니다."}, status_code=400)
    has_prev = conn.execute(
        "SELECT 1 FROM erp_docs WHERE company_id=? AND status='done' AND slip_date<? AND slip_date != ''", (book, f"{year}-01-01")
    ).fetchone()
    if has_prev and not _fiscal_closed(conn, book, year - 1):
        return JSONResponse({"error": f"{year - 1}년을 먼저 마감해 주세요."}, status_code=400)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO fiscal_closings (company_id, year, status, closed_by, closed_at) VALUES (?,?,'closed',?,?)
           ON CONFLICT(company_id, year) DO UPDATE SET status='closed', closed_by=excluded.closed_by,
               closed_at=excluded.closed_at, reopened_by=NULL, reopened_at=NULL, reopen_reason=NULL""",
        (book, year, u["id"], now),
    )
    log_activity(conn, u["id"], "close", "fiscal", year, str(year), f"{year}년 회기 마감")
    conn.commit()
    return JSONResponse({"ok": True})


@router.delete("/fi/fiscal/{year}")
async def fiscal_reopen(year: int, reason: str = Form(...), password: str = Form(...),
                        u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    row = conn.execute("SELECT password FROM users WHERE id=?", (u["id"],)).fetchone()
    if not row or not verify_pw(password, row["password"]):
        return JSONResponse({"error": "비밀번호가 일치하지 않습니다."}, status_code=400)
    if not reason.strip():
        return JSONResponse({"error": "마감 취소 사유를 입력해 주세요."}, status_code=400)
    if not _fiscal_closed(conn, book, year):
        return JSONResponse({"error": "마감되지 않은 연도입니다."}, status_code=400)
    if _fiscal_closed(conn, book, year + 1):
        return JSONResponse({"error": f"{year + 1}년 마감을 먼저 취소해 주세요."}, status_code=400)
    conn.execute(
        """UPDATE fiscal_closings SET status='open', reopened_by=?, reopened_at=?, reopen_reason=?
           WHERE company_id=? AND year=?""",
        (u["id"], now_kst().strftime("%Y-%m-%d %H:%M:%S"), reason.strip(), book, year),
    )
    log_activity(conn, u["id"], "reopen", "fiscal", year, str(year), f"{year}년 회기 마감 취소: {reason.strip()}")
    conn.commit()
    return JSONResponse({"ok": True})
