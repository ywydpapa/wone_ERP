from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_login, templates
from core.payroll import INSURANCE_LABELS

router = APIRouter()


@router.get("/insurance-rates", response_class=HTMLResponse)
async def insurance_rates_page(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    rows = conn.execute(
        "SELECT id, rate_key, rate_value, effective_date, created_at "
        "FROM insurance_rates ORDER BY effective_date DESC, rate_key"
    ).fetchall()
    rows = [dict(r) for r in rows]
    for r in rows:
        r["label"] = INSURANCE_LABELS.get(r["rate_key"], r["rate_key"])
        r["is_amount"] = r["rate_key"] in ("pension_upper", "pension_lower")

    current = conn.execute("""
        SELECT r.rate_key, r.rate_value, r.effective_date
        FROM insurance_rates r
        INNER JOIN (
            SELECT rate_key, MAX(effective_date) AS max_date
            FROM insurance_rates GROUP BY rate_key
        ) latest ON r.rate_key = latest.rate_key AND r.effective_date = latest.max_date
        ORDER BY r.rate_key
    """).fetchall()
    current = [dict(r) for r in current]
    for r in current:
        r["label"] = INSURANCE_LABELS.get(r["rate_key"], r["rate_key"])
        r["is_amount"] = r["rate_key"] in ("pension_upper", "pension_lower")

    return templates.TemplateResponse(
        request=request,
        name="hr/insurance_rates.html",
        context={
            "request": request,
            "page_title": "4대보험 요율 관리",
            "user_name": user["name"],
            "user_role": user["role"],
            "rows": rows,
            "current": current,
            "insurance_labels": INSURANCE_LABELS,
        },
    )


@router.post("/insurance-rates")
async def insurance_rates_add(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
    rate_key: str = Form(...),
    rate_value: str = Form(...),
    effective_date: str = Form(...),
):
    if rate_key not in INSURANCE_LABELS:
        return RedirectResponse(url="/hr/insurance-rates", status_code=303)

    val = float(rate_value.replace(",", ""))

    conn.execute(
        "INSERT INTO insurance_rates (rate_key, rate_value, effective_date) VALUES (?,?,?)",
        (rate_key, val, effective_date),
    )
    conn.commit()
    return RedirectResponse(url="/hr/insurance-rates", status_code=303)
