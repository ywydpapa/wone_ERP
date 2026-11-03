from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from core import deemed_interest
from core.books import require_book
from core.deps import get_db, templates
from core.export import csv_response
from core.tz import today_kst

router = APIRouter()


@router.get("/tax/deemed-interest", response_class=HTMLResponse)
async def tax_deemed_interest(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                              year: int = 0, rate: str = ""):
    year = year or today_kst().year
    rate = rate or deemed_interest.DEFAULT_RATE
    r = deemed_interest.calc(conn, u["book"], year, rate)

    if request.query_params.get("export") == "csv":
        rows = [[row["partner_name"], row["jeoksu"], row["deemed"], row["booked"], row["diff"], row["add"]]
                for row in r["rows"]]
        rows.append(["합계", r["total"]["jeoksu"], r["total"]["deemed"], r["total"]["booked"],
                     r["total"]["diff"], r["total"]["add"]])
        return csv_response(["거래처", "적수", "인정이자", "계상이자", "차이", "익금산입"], rows,
                            "deemed_interest.csv")

    return templates.TemplateResponse(request=request, name="erp/tax_deemed_interest.html", context={
        "request": request, "page_title": "가지급금 인정이자", "user_name": u["name"],
        "year": year, "rate": rate, "r": r,
    })
