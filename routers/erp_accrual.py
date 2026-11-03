import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core import accruals, books
from core.books import require_book
from core.deps import get_db, templates
from core.erp_log import log_activity
from core.export import csv_response
from core.tz import now_kst, today_kst
from routers._helpers import can_write

router = APIRouter()

KIND_OPTS = (("prepaid", "선급비용"), ("accrued", "미지급비용"))


def _default_ym():
    return today_kst().strftime("%Y-%m")


def _ym_param(request):
    ym = request.query_params.get("ym", "")
    return ym if accruals.valid_ym(ym) else _default_ym()


# lines_json엔 계정명/거래처명 미포함. 조회로 채움
def _display_lines(conn, book, lines):
    out = []
    for l in lines:
        acct = conn.execute("SELECT name FROM accounts WHERE company_id=? AND code=?", (book, l["code"])).fetchone()
        pname = ""
        if l.get("partner_id"):
            p = conn.execute("SELECT name FROM partners WHERE id=?", (l["partner_id"],)).fetchone()
            pname = p["name"] if p else ""
        out.append({"code": l["code"], "account_name": f"[{l['code']}] {acct['name']}" if acct else l["code"],
                    "debit": l.get("debit", 0), "credit": l.get("credit", 0), "partner": pname,
                    "summary": l.get("summary", ""), "dept": l.get("dept", "")})
    return out


ACCRUAL_SORTS = {"kind": "a.kind", "start": "a.start_ym", "end": "a.end_ym", "amount": "a.amount"}


def _accrual_rows(conn, book, sort="", dir=""):
    order = ACCRUAL_SORTS.get(sort)
    order_sql = f"ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, a.id DESC" if order else "ORDER BY a.id DESC"
    rows = [dict(r) for r in conn.execute(
        f"""SELECT a.*, ac.name AS expense_name, p.name AS partner_name FROM accruals a
            LEFT JOIN accounts ac ON ac.company_id=a.company_id AND ac.code=a.expense_code
            LEFT JOIN partners p ON p.id=a.partner_id
            WHERE a.company_id=? {order_sql}""", (book,)
    ).fetchall()]
    for r in rows:
        r["remaining"] = accruals.remain(conn, r)
    return rows


@router.get("/accruals", response_class=HTMLResponse)
async def accrual_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                        sort: str = "", dir: str = "", export: str = ""):
    book = u["book"]
    rows = _accrual_rows(conn, book, sort, dir)

    if export == "csv":
        csv_rows = [[
            dict(KIND_OPTS).get(r["kind"], r["kind"]), f"{r['expense_code']} {r['expense_name'] or ''}".strip(),
            r["partner_name"] or "", r["amount"], f"{r['start_ym']} ~ {r['end_ym']}", r["remaining"],
            "중지" if r["status"] == "stopped" else "진행",
        ] for r in rows]
        return csv_response(["구분", "비용계정", "거래처", "금액", "배분기간", "잔여", "상태"], csv_rows, "accruals.csv")

    return templates.TemplateResponse(request=request, name="erp/accrual_list.html", context={
        "request": request, "page_title": "기간 배분", "user_name": u["name"],
        "rows": rows, "ym": _ym_param(request), "can_write": can_write(u),
        "sort": sort, "dir": dir,
        "saved": request.query_params.get("saved") == "1", "stopped": request.query_params.get("stopped") == "1",
        "created": request.query_params.get("created", ""), "skipped": request.query_params.get("skipped", ""),
        "gen_error": request.query_params.get("gen_error", ""),
    })


@router.get("/accruals/new", response_class=HTMLResponse)
async def accrual_new(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return RedirectResponse("/accruals", status_code=303)
    book = u["book"]
    return templates.TemplateResponse(request=request, name="erp/accrual_form.html", context={
        "request": request, "page_title": "기간 배분 등록", "user_name": u["name"],
        "kind_opts": KIND_OPTS, "cost_accts": books.cost_accts(conn, book),
        "partners": books.partner_opts(conn, book), "depts": books.dept_names(conn, book),
    })


@router.post("/accruals")
async def accrual_create(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    f = await request.form()
    kind = f.get("kind", "")
    expense_code = f.get("expense_code", "").strip()
    amount = int(str(f.get("amount", 0) or 0).replace(",", ""))
    start_ym, end_ym = f.get("start_ym", ""), f.get("end_ym", "")
    pid = f.get("partner_id", "")
    partner_id = int(pid) if pid.isdigit() else None
    dept = f.get("dept", "").strip()
    memo = f.get("memo", "").strip()

    if kind not in dict(KIND_OPTS):
        return JSONResponse({"error": "구분을 선택해 주세요."}, status_code=400)
    if not conn.execute(
        "SELECT 1 FROM accounts WHERE company_id=? AND code=? AND category='비용' AND is_active=1", (book, expense_code)
    ).fetchone():
        return JSONResponse({"error": "비용 계정을 선택해 주세요."}, status_code=400)
    if amount <= 0:
        return JSONResponse({"error": "금액을 입력해 주세요."}, status_code=400)
    if not accruals.valid_ym(start_ym) or not accruals.valid_ym(end_ym) or start_ym > end_ym:
        return JSONResponse({"error": "배분 기간을 확인해 주세요."}, status_code=400)

    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    aid = conn.execute(
        """INSERT INTO accruals (company_id, kind, expense_code, amount, start_ym, end_ym, partner_id, dept, memo,
               status, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,'active',?,?)""",
        (book, kind, expense_code, amount, start_ym, end_ym, partner_id, dept, memo, u["id"], now),
    ).lastrowid
    log_activity(conn, u["id"], "create", "accrual", aid, expense_code, f"기간 배분 등록 {memo or expense_code}")
    conn.commit()
    return RedirectResponse("/accruals?saved=1", status_code=303)


@router.post("/accruals/{accrual_id}/stop")
async def accrual_stop(accrual_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    if not conn.execute("SELECT 1 FROM accruals WHERE id=? AND company_id=?", (accrual_id, book)).fetchone():
        return JSONResponse({"error": "대상을 찾을 수 없습니다."}, status_code=404)
    conn.execute("UPDATE accruals SET status='stopped' WHERE id=?", (accrual_id,))
    conn.commit()
    return RedirectResponse("/accruals?stopped=1", status_code=303)


@router.post("/accruals/generate")
async def accrual_generate(ym: str = Form(...), u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    if not accruals.valid_ym(ym):
        return JSONResponse({"error": "대상 월을 확인해 주세요."}, status_code=400)
    created, skipped, errors = accruals.run_accruals(conn, u["book"], u["id"], ym)
    conn.commit()
    url = f"/accruals?ym={ym}&created={created}&skipped={skipped}"
    if errors:
        url += f"&gen_error={quote(errors[0])}"
    return RedirectResponse(url, status_code=303)


RECURRING_SORTS = {"title": "title", "start": "start_ym", "end": "end_ym", "day": "day"}


def _recurring_rows(conn, book, sort="", dir=""):
    order = RECURRING_SORTS.get(sort)
    order_sql = f"ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, id DESC" if order else "ORDER BY id DESC"
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM recurring_slips WHERE company_id=? {order_sql}", (book,)
    ).fetchall()]


@router.get("/recurring", response_class=HTMLResponse)
async def recurring_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                          sort: str = "", dir: str = "", export: str = ""):
    book = u["book"]
    rows = _recurring_rows(conn, book, sort, dir)

    if export == "csv":
        csv_rows = [[
            r["title"], "말일" if r["day"] == 0 else f"{r['day']}일",
            f"{r['start_ym']} ~ {r['end_ym']}", "중지" if r["status"] == "stopped" else "진행",
        ] for r in rows]
        return csv_response(["제목", "결제일", "기간", "상태"], csv_rows, "recurring_slips.csv")

    return templates.TemplateResponse(request=request, name="erp/recurring_list.html", context={
        "request": request, "page_title": "반복전표", "user_name": u["name"],
        "rows": rows, "ym": _ym_param(request), "can_write": can_write(u),
        "sort": sort, "dir": dir,
        "saved": request.query_params.get("saved") == "1", "stopped": request.query_params.get("stopped") == "1",
        "created": request.query_params.get("created", ""), "skipped": request.query_params.get("skipped", ""),
        "gen_error": request.query_params.get("gen_error", ""),
    })


@router.get("/recurring/new", response_class=HTMLResponse)
async def recurring_new(request: Request, from_slip: int = 0, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return RedirectResponse("/recurring", status_code=303)
    book = u["book"]
    doc = conn.execute(
        "SELECT id, title FROM erp_docs WHERE id=? AND company_id=? AND status='done'", (from_slip, book)
    ).fetchone()
    if not doc:
        return RedirectResponse("/slip_list", status_code=303)
    lines = [dict(r) for r in conn.execute(
        """SELECT account_code AS code, account_name, debit, credit, partner_id, partner, summary, dept
           FROM slip_lines WHERE doc_id=? ORDER BY line_no""", (doc["id"],)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/recurring_form.html", context={
        "request": request, "page_title": "반복전표 등록", "user_name": u["name"],
        "title": doc["title"], "lines": lines,
        "lines_json": json.dumps([{"code": l["code"], "debit": l["debit"], "credit": l["credit"],
                                    "partner_id": l["partner_id"], "summary": l["summary"], "dept": l["dept"] or ""}
                                   for l in lines], ensure_ascii=False),
        "ym": _default_ym(),
    })


@router.post("/recurring")
async def recurring_create(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    f = await request.form()
    title = f.get("title", "").strip()
    day_raw = f.get("day", "")
    start_ym, end_ym = f.get("start_ym", ""), f.get("end_ym", "")
    lines_json = f.get("lines_json", "")

    if not title:
        return JSONResponse({"error": "제목을 입력해 주세요."}, status_code=400)
    if not day_raw.isdigit() or not 0 <= int(day_raw) <= 28:
        return JSONResponse({"error": "결제일을 확인해 주세요."}, status_code=400)
    day = int(day_raw)
    if not accruals.valid_ym(start_ym) or not accruals.valid_ym(end_ym) or start_ym > end_ym:
        return JSONResponse({"error": "반복 기간을 확인해 주세요."}, status_code=400)
    try:
        lines = json.loads(lines_json)
    except ValueError:
        return JSONResponse({"error": "전표 라인을 확인해 주세요."}, status_code=400)
    err = books.check_lines(conn, book, lines)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    rid = conn.execute(
        """INSERT INTO recurring_slips (company_id, title, day, lines_json, start_ym, end_ym, status,
               created_by, created_at)
           VALUES (?,?,?,?,?,?,'active',?,?)""",
        (book, title, day, lines_json, start_ym, end_ym, u["id"], now),
    ).lastrowid
    log_activity(conn, u["id"], "create", "recurring", rid, title, f"반복전표 등록 {title}")
    conn.commit()
    return RedirectResponse("/recurring?saved=1", status_code=303)


@router.get("/recurring/{recurring_id}/edit", response_class=HTMLResponse)
async def recurring_edit(request: Request, recurring_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    row = conn.execute("SELECT * FROM recurring_slips WHERE id=? AND company_id=?", (recurring_id, book)).fetchone()
    if not row:
        return HTMLResponse("<h2>반복전표를 찾을 수 없습니다</h2>", status_code=404)
    if not can_write(u):
        return RedirectResponse("/recurring", status_code=303)
    row = dict(row)
    return templates.TemplateResponse(request=request, name="erp/recurring_form.html", context={
        "request": request, "page_title": "반복전표 수정", "user_name": u["name"],
        "edit_mode": True, "row": row, "title": row["title"],
        "lines": _display_lines(conn, book, json.loads(row["lines_json"])), "lines_json": row["lines_json"],
        "ym": _default_ym(),
    })


@router.post("/recurring/{recurring_id}")
async def recurring_update(request: Request, recurring_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    if not conn.execute("SELECT 1 FROM recurring_slips WHERE id=? AND company_id=?", (recurring_id, book)).fetchone():
        return JSONResponse({"error": "대상을 찾을 수 없습니다."}, status_code=404)
    f = await request.form()
    title = f.get("title", "").strip()
    day_raw = f.get("day", "")
    start_ym, end_ym = f.get("start_ym", ""), f.get("end_ym", "")

    if not title:
        return JSONResponse({"error": "제목을 입력해 주세요."}, status_code=400)
    if not day_raw.isdigit() or not 0 <= int(day_raw) <= 28:
        return JSONResponse({"error": "결제일을 확인해 주세요."}, status_code=400)
    if not accruals.valid_ym(start_ym) or not accruals.valid_ym(end_ym) or start_ym > end_ym:
        return JSONResponse({"error": "반복 기간을 확인해 주세요."}, status_code=400)

    conn.execute(
        "UPDATE recurring_slips SET title=?, day=?, start_ym=?, end_ym=? WHERE id=?",
        (title, int(day_raw), start_ym, end_ym, recurring_id),
    )
    conn.commit()
    return RedirectResponse("/recurring?saved=1", status_code=303)


@router.post("/recurring/{recurring_id}/stop")
async def recurring_stop(recurring_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    book = u["book"]
    if not conn.execute("SELECT 1 FROM recurring_slips WHERE id=? AND company_id=?", (recurring_id, book)).fetchone():
        return JSONResponse({"error": "대상을 찾을 수 없습니다."}, status_code=404)
    conn.execute("UPDATE recurring_slips SET status='stopped' WHERE id=?", (recurring_id,))
    conn.commit()
    return RedirectResponse("/recurring?stopped=1", status_code=303)


@router.post("/recurring/generate")
async def recurring_generate(ym: str = Form(...), u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    if not accruals.valid_ym(ym):
        return JSONResponse({"error": "대상 월을 확인해 주세요."}, status_code=400)
    created, skipped, errors = accruals.run_recurring(conn, u["book"], u["id"], ym)
    conn.commit()
    url = f"/recurring?ym={ym}&created={created}&skipped={skipped}"
    if errors:
        url += f"&gen_error={quote(errors[0])}"
    return RedirectResponse(url, status_code=303)
