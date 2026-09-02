from datetime import date

from core.tz import now_kst

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_client_with_company, templates
from core.attendance import get_company_workers

router = APIRouter(prefix="/client")


@router.get("/evaluations", response_class=HTMLResponse)
async def eval_list(
    request: Request,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    year_filter = request.query_params.get("year", "")
    quarter_filter = request.query_params.get("quarter", "")

    company_id = user["company_id"]
    sql = """SELECT we.*, e.name as emp_name, e.dept
             FROM worker_evaluations we
             JOIN employees e ON we.employee_id = e.id
             WHERE we.company_id = ?"""
    params = [company_id]
    if year_filter:
        sql += " AND we.eval_year = ?"
        params.append(int(year_filter))
    if quarter_filter:
        sql += " AND we.eval_quarter = ?"
        params.append(int(quarter_filter))
    sql += " ORDER BY we.eval_year DESC, we.eval_quarter DESC, e.name"
    rows = conn.execute(sql, params).fetchall()
    evals = [dict(r) for r in rows]

    year_rows = conn.execute(
        "SELECT DISTINCT eval_year FROM worker_evaluations WHERE company_id=? ORDER BY eval_year DESC",
        (company_id,),
    ).fetchall()
    years = [r["eval_year"] for r in year_rows]
    if not years:
        years = [now_kst().year]

    return templates.TemplateResponse(
        request=request, name="client/eval_list.html", context={
            "request": request,
            "page_title": "근로자 평가",
            "user_name": user["user_name"],
            "evals": evals,
            "years": years,
            "year_filter": year_filter,
            "quarter_filter": quarter_filter,
        }
    )


@router.get("/evaluations/new", response_class=HTMLResponse)
async def eval_new(
    request: Request,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
    workers = get_company_workers(conn, company_id) if company_id else []

    now = now_kst()
    current_quarter = (now.month - 1) // 3 + 1

    return templates.TemplateResponse(
        request=request, name="client/eval_form.html", context={
            "request": request,
            "page_title": "근로자 평가 등록",
            "user_name": user["user_name"],
            "workers": workers,
            "current_year": now.year,
            "current_quarter": current_quarter,
        }
    )


@router.post("/evaluations")
async def eval_create(
    request: Request,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
    employee_id: int = Form(...),
    eval_year: int = Form(...),
    eval_quarter: int = Form(...),
    work_quality: int = Form(3),
    work_attitude: int = Form(3),
    cooperation: int = Form(3),
    punctuality: int = Form(3),
    strengths: str = Form(""),
    improvements: str = Form(""),
    comments: str = Form(""),
):
    overall = (work_quality + work_attitude + cooperation + punctuality) / 4

    company_id = user["company_id"]
    conn.execute("""
        INSERT OR REPLACE INTO worker_evaluations
            (employee_id, company_id, eval_year, eval_quarter,
             work_quality, work_attitude, cooperation, punctuality,
             overall_score, strengths, improvements, comments,
             evaluator_id, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))
    """, (
        employee_id, company_id, eval_year, eval_quarter,
        work_quality, work_attitude, cooperation, punctuality,
        overall, strengths, improvements, comments,
        user["user_id"],
    ))
    conn.commit()

    return RedirectResponse(url="/client/evaluations", status_code=303)


@router.get("/evaluations/{eval_id}", response_class=HTMLResponse)
async def eval_detail(
    request: Request,
    eval_id: int,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
    row = conn.execute(
        """SELECT we.*, e.name as emp_name, e.dept
           FROM worker_evaluations we
           JOIN employees e ON we.employee_id = e.id
           WHERE we.id = ? AND we.company_id = ?""",
        (eval_id, company_id),
    ).fetchone()
    if not row:
        return RedirectResponse(url="/client/evaluations", status_code=303)
    ev = dict(row)

    return templates.TemplateResponse(
        request=request, name="client/eval_detail.html", context={
            "request": request,
            "page_title": f"{ev['emp_name']} 평가 상세",
            "user_name": user["user_name"],
            "eval": ev,
        }
    )


@router.get("/contract", response_class=HTMLResponse)
async def contract(
    request: Request,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
    row = conn.execute(
        """SELECT name, business_no, contract_start, contract_end,
                  status, contact_name, contact_phone, contact_email
           FROM client_companies WHERE id=?""",
        (company_id,),
    ).fetchone()
    company = dict(row) if row else {}

    worker_count = conn.execute(
        "SELECT COUNT(*) FROM employees WHERE company_id=? AND status='active'",
        (company_id,),
    ).fetchone()[0]

    days_left = None
    if company.get("contract_end"):
        try:
            end = date.fromisoformat(company["contract_end"])
            days_left = (end - date.today()).days
        except ValueError:
            pass

    return templates.TemplateResponse(
        request=request, name="client/contract.html", context={
            "request": request,
            "page_title": "계약 관리",
            "user_name": user["user_name"],
            "company": company,
            "worker_count": worker_count,
            "days_left": days_left,
        }
    )
