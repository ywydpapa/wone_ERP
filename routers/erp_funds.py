from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from core import funds
from core.books import require_book
from core.deps import get_db, templates
from core.export import csv_response
from core.tz import today_kst

router = APIRouter()

MONTHS_OPTS = (1, 3, 6)


@router.get("/ledger/daily-funds", response_class=HTMLResponse)
async def daily_funds(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                      day: str = "", export: str = ""):
    book = u["book"]
    day = day or today_kst().isoformat()
    data = funds.daily_funds(conn, book, day)

    if export == "csv":
        csv_rows = [[r["label"], r["prev"], r["in"], r["out"], r["cur"]] for r in data["rows"]]
        csv_rows.append(["합계", data["totals"]["prev"], data["totals"]["in"], data["totals"]["out"],
                         data["totals"]["cur"]])
        return csv_response(["계좌", "전일잔액", "입금", "출금", "당일잔액"], csv_rows, "daily_funds.csv")

    return templates.TemplateResponse(request=request, name="erp/ledger_daily_funds.html", context={
        "request": request, "page_title": "자금일보", "user_name": u["name"],
        "day": day, "rows": data["rows"], "totals": data["totals"], "lines": data["lines"],
    })


@router.get("/ledger/cash-plan", response_class=HTMLResponse)
async def cash_plan(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                    as_of: str = "", months: int = 3):
    book = u["book"]
    as_of = as_of or today_kst().isoformat()
    if months not in MONTHS_OPTS:
        months = 3
    data = funds.cash_plan(conn, book, as_of, months)

    return templates.TemplateResponse(request=request, name="erp/ledger_cash_plan.html", context={
        "request": request, "page_title": "자금계획", "user_name": u["name"],
        "as_of": as_of, "months": months, "months_opts": MONTHS_OPTS,
        "opening": data["opening"], "rows": data["rows"], "items": data["items"], "end": data["end"],
    })
