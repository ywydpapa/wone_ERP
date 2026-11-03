from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core import equity
from core.books import require_book, balance_sheet_data, income_statement_data
from core.deps import get_db, templates
from core.export import csv_response
from core.tz import today_kst
from routers._helpers import can_write

router = APIRouter()

EARLY_DATE = "1900-01-01"


def _int(v):
    v = str(v or "0").replace(",", "").strip()
    if not v.lstrip("-").isdigit():
        raise ValueError
    return int(v)


# 전기이월 미처분이익잉여금. 재무상태표 자본 항목 중 375/377 기초 잔액(이익준비금 등 적립금 제외)
def _re_opening(conn, book, year):
    _, _, _, equity_list, *_ = balance_sheet_data(conn, book, f"{year - 1}-12-31")
    item = next((it for it in equity_list if it["code"] in ("375", "377")), None)
    return item["balance"] if item else 0


@router.get("/report/retained-earnings", response_class=HTMLResponse)
async def retained_earnings(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    qp = request.query_params
    year = int(qp.get("year")) if qp.get("year", "").isdigit() else today_kst().year
    try:
        reinvest = _int(qp.get("reinvest", "0"))
        legal_reserve = _int(qp.get("legal_reserve", "0"))
        cash_div = _int(qp.get("cash_div", "0"))
        other_reserve = _int(qp.get("other_reserve", "0"))
    except ValueError:
        reinvest = legal_reserve = cash_div = other_reserve = 0

    opening = _re_opening(conn, book, year)
    net_income = income_statement_data(conn, book, f"{year}-01-01", f"{year}-12-31")[3]["net_income"]
    available = opening + net_income
    pool = available + reinvest
    appropriated = legal_reserve + cash_div + other_reserve
    carry_forward = pool - appropriated

    existing = equity.get_approp(conn, book, year)
    warning = None if existing else equity.reserve_warn(conn, book, year, legal_reserve, cash_div)

    return templates.TemplateResponse(request=request, name="erp/retained_earnings.html", context={
        "request": request, "page_title": "이익잉여금처분계산서", "user_name": u["name"],
        "year": year, "opening": opening, "net_income": net_income, "available": available,
        "reinvest": reinvest, "pool": pool, "legal_reserve": legal_reserve, "cash_div": cash_div,
        "other_reserve": other_reserve, "appropriated": appropriated, "carry_forward": carry_forward,
        "existing": existing, "warning": warning, "can_write": can_write(u),
        "today": today_kst().isoformat(),
    })


@router.post("/report/retained-earnings")
async def retained_earnings_approve(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    form = await request.form()
    try:
        year = int(form.get("year", ""))
    except ValueError:
        return JSONResponse({"error": "연도를 확인해 주세요."}, status_code=400)
    approve_date = form.get("approve_date", "").strip()
    try:
        date.fromisoformat(approve_date)
    except ValueError:
        return JSONResponse({"error": "주총일을 확인해 주세요."}, status_code=400)
    try:
        legal_reserve = _int(form.get("legal_reserve", "0"))
        cash_div = _int(form.get("cash_div", "0"))
        other_reserve = _int(form.get("other_reserve", "0"))
    except ValueError:
        return JSONResponse({"error": "입력 값을 확인해 주세요."}, status_code=400)
    try:
        equity.approve(conn, u["book"], u["id"], year, approve_date, legal_reserve, cash_div, other_reserve)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return RedirectResponse(f"/report/retained-earnings?year={year}", status_code=303)


@router.post("/report/retained-earnings/{year}/cancel")
async def retained_earnings_cancel(request: Request, year: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    if not can_write(u):
        return JSONResponse({"error": "권한이 없습니다."}, status_code=403)
    form = await request.form()
    rev_date = form.get("rev_date", "").strip()
    try:
        date.fromisoformat(rev_date)
    except ValueError:
        return JSONResponse({"error": "역분개 일자를 확인해 주세요."}, status_code=400)
    try:
        equity.cancel(conn, u["book"], u["id"], year, rev_date)
    except LookupError:
        return JSONResponse({"error": "처분 확정 내역을 찾을 수 없습니다."}, status_code=404)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return JSONResponse({"ok": True})


def _surplus_codes(conn, book):
    return [r["code"] for r in conn.execute(
        """SELECT code FROM accounts WHERE company_id=? AND category='자본' AND is_active=1
               AND code NOT IN ('331','341','351','356','375','377') ORDER BY code""",
        (book,)).fetchall()]


def _group_balance(conn, book, codes, as_of):
    return sum(equity.acct_balance(conn, book, c, as_of) for c in codes)


# 이익잉여금(341,351,356,375,377) 실제 잔액 + 손익 미결산분(누적 당기순이익). 재무상태표 자본 합계와 일치하는 기준
def _retained_balance(conn, book, as_of):
    real = sum(equity.acct_balance(conn, book, c, as_of) for c in equity.RE_ACCOUNTS)
    net_income = income_statement_data(conn, book, EARLY_DATE, as_of)[3]["net_income"]
    return real + net_income


def _equity_changes_data(conn, book, year):
    y_start, y_end, prev_end = f"{year}-01-01", f"{year}-12-31", f"{year - 1}-12-31"
    cols = ("capital", "surplus", "retained")
    cs_codes = _surplus_codes(conn, book)

    opening = {"capital": equity.acct_balance(conn, book, "331", prev_end),
               "surplus": _group_balance(conn, book, cs_codes, prev_end),
               "retained": _retained_balance(conn, book, prev_end)}
    closing = {"capital": equity.acct_balance(conn, book, "331", y_end),
               "surplus": _group_balance(conn, book, cs_codes, y_end),
               "retained": _retained_balance(conn, book, y_end)}
    net_income = income_statement_data(conn, book, y_start, y_end)[3]["net_income"]
    dividend = equity.approp_amount(conn, book, y_start, y_end)
    paid_in = equity.net_change(conn, book, "331", y_start, y_end)

    def _row(label, **amounts):
        r = {c: amounts.get(c, 0) for c in cols}
        r["label"] = label
        r["total"] = sum(r[c] for c in cols)
        return r

    rows = [_row("기초", **opening)]
    rows.append(_row("연차배당", retained=-dividend))
    rows.append(_row("당기순이익", retained=net_income))
    rows.append(_row("유상증자", capital=paid_in))
    other = {c: closing[c] - opening[c] - sum(r[c] for r in rows[1:]) for c in cols}
    rows.append(_row("기타", **other))
    rows.append(_row("기말", **closing))
    return rows, cols


@router.get("/report/equity-changes", response_class=HTMLResponse)
async def equity_changes(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    qp = request.query_params
    year = int(qp.get("year")) if qp.get("year", "").isdigit() else today_kst().year
    rows, cols = _equity_changes_data(conn, book, year)

    return templates.TemplateResponse(request=request, name="erp/equity_changes.html", context={
        "request": request, "page_title": "자본변동표", "user_name": u["name"],
        "year": year, "rows": rows, "cols": cols,
    })


@router.get("/report/equity-changes/excel")
async def equity_changes_excel(u: dict = Depends(require_book), conn=Depends(get_db), year: str = ""):
    book = u["book"]
    year = int(year) if year.isdigit() else today_kst().year
    rows, cols = _equity_changes_data(conn, book, year)
    labels = {"capital": "자본금", "surplus": "자본잉여금", "retained": "이익잉여금"}
    csv_rows = [[r["label"]] + [r[c] for c in cols] + [r["total"]] for r in rows]
    return csv_response(["구분"] + [labels[c] for c in cols] + ["합계"], csv_rows, "equity_changes.csv")
