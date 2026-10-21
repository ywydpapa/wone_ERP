from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core import assets, audit, books, stock
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


def _master_dept(conn, book, name):
    if name and conn.execute("SELECT 1 FROM depts WHERE company_id=? AND name=?", (book, name)).fetchone():
        return name
    return ""


def _asset_accounts(conn, book):
    q = ",".join("?" * len(assets.ACCUM))
    return conn.execute(
        f"SELECT code, name FROM accounts WHERE company_id=? AND code IN ({q}) ORDER BY code", (book, *assets.ACCUM)
    ).fetchall()


@router.get("/fa", response_class=HTMLResponse)
async def fa_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    year = _year(request)
    status = request.query_params.get("status", "active")
    sql = """SELECT f.*, a.name AS account_name,
                    (SELECT COALESCE(SUM(c.amount), 0) FROM fa_capex c
                     WHERE c.asset_id=f.id AND substr(c.date, 1, 4) <= ?) AS capex_total
             FROM fixed_assets f
             LEFT JOIN accounts a ON a.company_id=f.company_id AND a.code=f.account_code
             WHERE f.company_id=?"""
    args = [str(year), u["book"]]
    if status in ("active", "disposed"):
        sql += " AND f.status=?"
        args.append(status)
    tot = {"cost": 0, "open": 0, "cur": 0, "end": 0, "left": 0}
    rows = []
    cur_acc, sub = None, {}
    for f in conn.execute(sql + " ORDER BY f.account_code, f.code", args).fetchall():
        d = assets.depr(conn, f, year)
        r = dict(f, cur=d["amount"], accum=d["accum"], end=d["accum"] + d["amount"], posted=d["posted"], error=d["error"])
        r["left"] = f["acq_cost"] + f["capex_total"] - r["end"]
        if r["account_code"] != cur_acc:
            if cur_acc is not None:
                rows.append({"_type": "subtotal", **sub})
            sub = {"account_name": f"{r['account_code']} {r['account_name'] or ''}",
                   "cost": 0, "open": 0, "cur": 0, "end": 0, "left": 0}
            cur_acc = r["account_code"]
        sub["cost"] += f["acq_cost"]
        sub["open"] += r["accum"]
        sub["cur"] += r["cur"]
        sub["end"] += r["end"]
        sub["left"] += r["left"]
        rows.append({"_type": "row", **r})
        tot["cost"] += f["acq_cost"]
        tot["open"] += r["accum"]
        tot["cur"] += r["cur"]
        tot["end"] += r["end"]
        tot["left"] += r["left"]
    if cur_acc is not None:
        rows.append({"_type": "subtotal", **sub})
    return templates.TemplateResponse(request=request, name="erp/fa_asset_list.html", context={
        "request": request, "page_title": "고정자산 대장", "rows": rows, "tot": tot,
        "year": year, "status": status, "can_write": _writer(u), "saved": request.query_params.get("saved") == "1",
    })


def _dept_opts(conn, book):
    return conn.execute(
        "SELECT name FROM depts WHERE company_id=? AND is_active=1 ORDER BY sort, name", (book,)
    ).fetchall()


def _asset_capex(conn, asset_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM fa_capex WHERE asset_id=? ORDER BY date", (asset_id,)
    ).fetchall()]


def _asset_form(request, conn, u, asset):
    capex = _asset_capex(conn, asset["id"]) if asset else []
    return templates.TemplateResponse(request=request, name="erp/fa_asset_form.html", context={
        "request": request, "page_title": "고정자산 수정" if asset else "고정자산 등록",
        "a": asset or {}, "accounts": _asset_accounts(conn, u["book"]), "methods": assets.METHODS,
        "depts": _dept_opts(conn, u["book"]),
        "locked": bool(asset and conn.execute("SELECT 1 FROM fa_depr WHERE asset_id=?", (asset["id"],)).fetchone()),
        "capex": capex, "capex_total": sum(c["amount"] for c in capex),
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
        "dept": f.get("dept", "").strip(), "code": f.get("code", "").strip(),
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
               open_accum, open_year, dept, status, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,'active',?)""",
        (book, a["code"], a["name"], a["account_code"], a["acq_date"], a["acq_cost"], a["life_years"], a["method"],
         a["open_accum"], a["open_year"], a["dept"], u["id"]),
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
    # 상태/처분일은 처분 화면에서만 변경
    conn.execute(
        """UPDATE fixed_assets SET name=?, account_code=?, acq_date=?, acq_cost=?, life_years=?, method=?,
               open_accum=?, open_year=?, dept=? WHERE id=?""",
        (a["name"], a["account_code"], a["acq_date"], a["acq_cost"], a["life_years"], a["method"],
         a["open_accum"], a["open_year"], a["dept"], fa_id),
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


@router.post("/fa/{fa_id}/capex")
async def fa_capex_add(request: Request, fa_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    a = conn.execute("SELECT * FROM fixed_assets WHERE id=? AND company_id=?", (fa_id, book)).fetchone()
    if not a:
        return JSONResponse({"error": "자산을 찾을 수 없습니다."}, status_code=404)
    if a["status"] == "disposed":
        return JSONResponse({"error": "처분된 자산에는 등록할 수 없습니다."}, status_code=400)

    f = await request.form()
    date = f.get("date", "")
    amount = _int(f.get("amount"))
    memo = f.get("memo", "").strip()
    if not _valid_date(date):
        return JSONResponse({"error": "지출일을 확인해 주세요."}, status_code=400)
    if date < a["acq_date"]:
        return JSONResponse({"error": "지출일은 취득일 이후여야 합니다."}, status_code=400)
    if amount <= 0:
        return JSONResponse({"error": "금액을 입력해 주세요."}, status_code=400)
    y = int(date[:4])
    if y <= a["open_year"] or conn.execute(
        "SELECT 1 FROM fa_depr WHERE asset_id=? AND year>=?", (fa_id, y)
    ).fetchone():
        return JSONResponse({"error": f"{y}년 상각이 이미 반영되었습니다. 상각 취소 후 등록해 주세요."}, status_code=400)

    conn.execute(
        "INSERT INTO fa_capex (company_id, asset_id, date, amount, memo, created_by) VALUES (?,?,?,?,?,?)",
        (book, fa_id, date, amount, memo, u["id"]),
    )
    log_activity(conn, u["id"], "create", "fixed_asset", fa_id, a["code"], f"자본적지출 등록 {amount:,}원")
    audit.log(conn, u["id"], "fa_capex", "fixed_asset", fa_id, f"{a['code']} {a['name']} 자본적지출 {amount:,}원",
              company_id=book)
    conn.commit()
    return RedirectResponse(f"/fa/{fa_id}?saved=1", status_code=303)


# 101 현금, 103 보통예금, 계정과목표상 미수금 계정
def _deposit_accounts(conn, book):
    return conn.execute(
        """SELECT code, name FROM accounts WHERE company_id=? AND is_active=1
           AND (code IN ('101','103') OR name='미수금') ORDER BY code""", (book,)
    ).fetchall()


@router.get("/fa/{fa_id}/disposal", response_class=HTMLResponse)
async def fa_disposal_form(request: Request, fa_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    a = conn.execute("SELECT * FROM fixed_assets WHERE id=? AND company_id=?", (fa_id, u["book"])).fetchone()
    if not a:
        return HTMLResponse("<h2>자산을 찾을 수 없습니다</h2>", status_code=404)
    if not _writer(u) or a["status"] == "disposed":
        return RedirectResponse("/fa", status_code=303)
    return templates.TemplateResponse(request=request, name="erp/fa_disposal_form.html", context={
        "request": request, "page_title": "고정자산 처분", "a": dict(a),
        "accounts": _deposit_accounts(conn, u["book"]), "today": today_kst().strftime("%Y-%m-%d"),
    })


@router.post("/fa/{fa_id}/disposal")
async def fa_dispose(request: Request, fa_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    a = conn.execute("SELECT * FROM fixed_assets WHERE id=? AND company_id=?", (fa_id, book)).fetchone()
    if not a:
        return JSONResponse({"error": "자산을 찾을 수 없습니다."}, status_code=404)
    if a["status"] == "disposed":
        return JSONResponse({"error": "이미 처분된 자산입니다."}, status_code=400)

    f = await request.form()
    disposed_date = f.get("disposed_date", "")
    if not _valid_date(disposed_date):
        return JSONResponse({"error": "처분일을 확인해 주세요."}, status_code=400)
    if disposed_date < a["acq_date"]:
        return JSONResponse({"error": "처분일은 취득일 이후여야 합니다."}, status_code=400)

    supply = _int(f.get("supply_amt"))
    vat = _int(f.get("vat_amt"))
    if supply < 0 or vat < 0:
        return JSONResponse({"error": "처분가액을 확인해 주세요."}, status_code=400)
    dep_accounts = {r["code"]: r["name"] for r in _deposit_accounts(conn, book)}
    deposit_code = f.get("deposit_code", "")
    # 폐기는 처분가액 0. 입금 계정 불필요
    if supply + vat > 0 and deposit_code not in dep_accounts:
        return JSONResponse({"error": "입금 계정을 선택해 주세요."}, status_code=400)
    pid = f.get("partner_id", "")
    pid = int(pid) if pid.isdigit() else None
    if dep_accounts.get(deposit_code) == "미수금" and not pid:
        return JSONResponse({"error": "미수금 처리 시 거래처를 선택해 주세요."}, status_code=400)
    if pid and not conn.execute("SELECT 1 FROM partners WHERE id=? AND company_id=?", (pid, book)).fetchone():
        return JSONResponse({"error": "거래처를 찾을 수 없습니다."}, status_code=400)

    year = int(disposed_date[:4])
    d = assets.depr(conn, dict(a, disposed_date=disposed_date), year)
    if d["error"]:
        return JSONResponse({"error": d["error"]}, status_code=400)
    if d["posted"]:
        return JSONResponse({"error": "처분 연도 상각이 이미 전기되었습니다."}, status_code=400)
    cur, prior = d["amount"], d["accum"]
    nbv = a["acq_cost"] - prior - cur
    diff = supply - nbv

    title = f"고정자산 처분 ({a['name']})"
    summary = f.get("summary", "").strip() or title
    dept = _master_dept(conn, book, a["dept"])
    lines = []
    if cur > 0:
        lines.append({"code": assets.DEPR_CODE, "debit": cur, "credit": 0, "summary": title, "dept": dept})
    if prior > 0:
        lines.append({"code": assets.ACCUM[a["account_code"]], "debit": prior, "credit": 0, "summary": title})
    if supply + vat > 0:
        lines.append({"code": deposit_code, "debit": supply + vat, "credit": 0, "partner_id": pid, "summary": summary})
    lines.append({"code": a["account_code"], "debit": 0, "credit": a["acq_cost"], "summary": title})
    if vat > 0:
        lines.append({"code": "255", "debit": 0, "credit": vat, "summary": title})
    if diff > 0:
        lines.append({"code": "914", "debit": 0, "credit": diff, "summary": title})
    elif diff < 0:
        lines.append({"code": "970", "debit": -diff, "credit": 0, "summary": title})

    try:
        doc_id = books.post(conn, book, u["id"], disposed_date, lines, title, "fa_disposal", fa_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    if cur > 0:
        conn.execute("INSERT INTO fa_depr (company_id, asset_id, year, amount, doc_id) VALUES (?,?,?,?,?)",
                     (book, fa_id, year, cur, doc_id))
    conn.execute("UPDATE fixed_assets SET status='disposed', disposed_date=? WHERE id=?", (disposed_date, fa_id))
    log_activity(conn, u["id"], "update", "fixed_asset", fa_id, a["code"], f"고정자산 처분 {a['name']}")
    audit.log(conn, u["id"], "fa_dispose", "fixed_asset", fa_id, f"{a['code']} {a['name']} 처분", company_id=book)
    conn.commit()
    return RedirectResponse("/fa?saved=1", status_code=303)


@router.delete("/fa/{fa_id}/disposal")
async def fa_dispose_cancel(fa_id: int, reason: str = Form(...), password: str = Form(...),
                            u: dict = Depends(require_book), conn=Depends(get_db)):
    if not _writer(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    a = conn.execute("SELECT * FROM fixed_assets WHERE id=? AND company_id=?", (fa_id, book)).fetchone()
    if not a:
        return JSONResponse({"error": "자산을 찾을 수 없습니다."}, status_code=404)
    if a["status"] != "disposed":
        return JSONResponse({"error": "처분된 자산이 아닙니다."}, status_code=400)
    row = conn.execute("SELECT password FROM users WHERE id=?", (u["id"],)).fetchone()
    if not row or not verify_pw(password, row["password"]):
        return JSONResponse({"error": "비밀번호가 일치하지 않습니다."}, status_code=400)
    if not reason.strip():
        return JSONResponse({"error": "취소 사유를 입력해 주세요."}, status_code=400)

    doc = conn.execute(
        """SELECT * FROM erp_docs WHERE company_id=? AND source_type='fa_disposal' AND source_id=?
           AND NOT EXISTS (SELECT 1 FROM erp_docs r WHERE r.reversal_of=erp_docs.id)""",
        (book, fa_id),
    ).fetchone()
    if doc:
        if books.period_closed(conn, book, doc["slip_date"]):
            return JSONResponse({"error": "마감된 회계기간의 처분은 취소할 수 없습니다."}, status_code=400)
        books.reverse(conn, doc["id"], u["id"], doc["slip_date"])
        conn.execute("DELETE FROM fa_depr WHERE doc_id=?", (doc["id"],))

    conn.execute("UPDATE fixed_assets SET status='active', disposed_date=NULL WHERE id=?", (fa_id,))
    log_activity(conn, u["id"], "update", "fixed_asset", fa_id, a["code"], f"고정자산 처분 취소 {a['name']}")
    audit.log(conn, u["id"], "fa_dispose_cancel", "fixed_asset", fa_id,
              f"{a['code']} {a['name']} 처분 취소: {reason.strip()}", company_id=book)
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
        # 처분 전표 등으로 이미 전기된 연도는 결산 대상에서 제외(중복 전기 방지)
        if d["error"] or (d["amount"] and not d["posted"]):
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
        by_dept = {}
        for a in d["assets"]:
            if not a["error"]:
                dept = _master_dept(conn, book, a["dept"])
                by_dept[dept] = by_dept.get(dept, 0) + a["amount"]
        for dept, amt in sorted(by_dept.items()):
            lines.append({"code": assets.DEPR_CODE, "debit": amt, "credit": 0, "summary": f"{year}년 감가상각비", "dept": dept})
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
    if not _closing_doc(conn, book, year):
        return JSONResponse({"error": "결산분개가 없습니다. 결산자료입력에서 먼저 반영해 주세요."}, status_code=400)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO fiscal_closings (company_id, year, status, closed_by, closed_at) VALUES (?,?,'closed',?,?)
           ON CONFLICT(company_id, year) DO UPDATE SET status='closed', closed_by=excluded.closed_by,
               closed_at=excluded.closed_at, reopened_by=NULL, reopened_at=NULL, reopen_reason=NULL""",
        (book, year, u["id"], now),
    )
    log_activity(conn, u["id"], "close", "fiscal", year, str(year), f"{year}년 회기 마감")
    audit.log(conn, u["id"], "fiscal_close", "fiscal", year, f"{year}년 회기 마감", company_id=book)
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
    audit.log(conn, u["id"], "fiscal_reopen", "fiscal", year, f"{year}년 회기 마감 취소: {reason.strip()}",
              company_id=book)
    conn.commit()
    return JSONResponse({"ok": True})
