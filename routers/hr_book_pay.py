from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core.tz import now_kst
from core.deps import get_db, templates
from core.books import book_emp, book_label, emp_book, require_hr_book
from core.pay_items import get_items, get_item, item_in_use, next_sort
from core.severance import calc_severance, calc_sev_tax
from core.export import csv_response

router = APIRouter()


# 급여항목 설정 (pay_items.company_id = book, 원 내부는 0)

@router.get("/pay-items", response_class=HTMLResponse)
async def pay_items_page(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book = user["book"]
    rows = get_items(conn, book, active_only=False)
    for r in rows:
        r["in_use"] = item_in_use(conn, r["id"])

    return templates.TemplateResponse(
        request=request, name="client/pay_items.html", context={
            "request": request,
            "page_title": "급여항목 설정",
            "user_name": user["name"],
            "book_name": book_label(conn, book),
            "items": rows,
            "error": request.query_params.get("error", ""),
        }
    )


@router.post("/pay-items")
async def pay_items_add(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
    code: str = Form(...),
    name: str = Form(...),
    taxable: int = Form(1),
    tax_free_code: str = Form(""),
    tax_free_limit: int = Form(0),
    ordinary: int = Form(0),
    avg_wage: int = Form(1),
    bonus: int = Form(0),
):
    book = user["book"]
    code = code.strip().upper()
    dup = conn.execute(
        "SELECT 1 FROM pay_items WHERE company_id=? AND code=?", (book, code)
    ).fetchone()
    if not code or not name.strip() or dup:
        return RedirectResponse(url="/pay-items?error=invalid", status_code=303)

    conn.execute(
        """INSERT INTO pay_items (company_id, code, name, kind, taxable, tax_free_code,
               tax_free_limit, ordinary, avg_wage, bonus, sort)
           VALUES (?,?,?,'지급',?,?,?,?,?,?,?)""",
        (book, code, name.strip(), taxable, tax_free_code.strip(), tax_free_limit,
         ordinary, avg_wage, bonus, next_sort(conn, book)),
    )
    conn.commit()
    return RedirectResponse(url="/pay-items", status_code=303)


@router.get("/pay-items/{item_id}/edit", response_class=HTMLResponse)
async def pay_items_edit_form(
    request: Request,
    item_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book = user["book"]
    item = get_item(conn, book, item_id)
    if not item:
        return RedirectResponse(url="/pay-items", status_code=303)
    return templates.TemplateResponse(
        request=request, name="client/pay_item_form.html", context={
            "request": request,
            "page_title": "급여항목 수정",
            "user_name": user["name"],
            "item": item,
        }
    )


@router.post("/pay-items/{item_id}")
async def pay_items_edit(
    request: Request,
    item_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
    name: str = Form(...),
    taxable: int = Form(1),
    tax_free_code: str = Form(""),
    tax_free_limit: int = Form(0),
    ordinary: int = Form(0),
    avg_wage: int = Form(1),
    bonus: int = Form(0),
):
    book = user["book"]
    item = get_item(conn, book, item_id)
    if not item:
        return JSONResponse({"error": "급여항목을 찾을 수 없습니다."}, status_code=404)

    conn.execute(
        """UPDATE pay_items SET name=?, taxable=?, tax_free_code=?, tax_free_limit=?,
               ordinary=?, avg_wage=?, bonus=? WHERE id=? AND company_id=?""",
        (name.strip(), taxable, tax_free_code.strip(), tax_free_limit, ordinary, avg_wage, bonus,
         item_id, book),
    )
    conn.commit()
    return RedirectResponse(url="/pay-items", status_code=303)


@router.post("/pay-items/{item_id}/deactivate")
async def pay_items_deactivate(
    item_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book = user["book"]
    item = get_item(conn, book, item_id)
    if not item:
        return RedirectResponse(url="/pay-items", status_code=303)
    conn.execute(
        "UPDATE pay_items SET active = CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=? AND company_id=?",
        (item_id, book),
    )
    conn.commit()
    return RedirectResponse(url="/pay-items", status_code=303)


@router.post("/pay-items/{item_id}/delete")
async def pay_items_delete(
    item_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book = user["book"]
    item = get_item(conn, book, item_id)
    if not item:
        return RedirectResponse(url="/pay-items", status_code=303)
    if item_in_use(conn, item_id):
        return RedirectResponse(url="/pay-items?error=in_use", status_code=303)
    conn.execute("DELETE FROM pay_items WHERE id=? AND company_id=?", (item_id, book))
    conn.commit()
    return RedirectResponse(url="/pay-items", status_code=303)


# 퇴직금

SEV_SORTS = {"name": ("name", ""), "hire": ("hire_date", ""), "tenure": ("tenure_days", 0),
             "avg": ("avg_salary", 0), "amount": ("amount", 0)}


@router.get("/severance/estimate", response_class=HTMLResponse)
async def severance_estimate_list(
    request: Request,
    sort: str = "",
    dir: str = "",
    export: str = "",
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    now = now_kst()
    base_date = request.query_params.get("base_date") or now.strftime("%Y-%m-%d")
    book = user["book"]

    emps = conn.execute(
        "SELECT id, name, employee_no, hire_date FROM employees WHERE status='active' AND company_id IS ? ORDER BY employee_no, name",
        (emp_book(book),),
    ).fetchall()

    rows = []
    for e in emps:
        sev = calc_severance(conn, e["id"], resign_date=base_date)
        if not sev:
            continue
        rows.append({
            "id": e["id"],
            "name": e["name"],
            "hire_date": e["hire_date"],
            "tenure_days": sev["tenure_days"],
            "avg_salary": sev["avg_salary"],
            "amount": sev["amount"],
        })

    field_default = SEV_SORTS.get(sort)
    if field_default:
        field, default = field_default
        rows.sort(key=lambda r: r[field] or default, reverse=dir == "desc")

    if export == "csv":
        data = [[r["name"], r["hire_date"] or "-", r["tenure_days"], r["avg_salary"], r["amount"]] for r in rows]
        return csv_response(["성명", "입사일", "근속일수", "1일 평균임금", "퇴직금 추계액"], data, "severance_estimate.csv")

    total_count = len(rows)
    sum_amount = sum(r["amount"] for r in rows)

    return templates.TemplateResponse(
        request=request,
        name="hr/severance_estimate_list.html",
        context={
            "request": request,
            "page_title": "퇴직금 추계액",
            "user_name": user["name"],
            "user_role": user["role"],
            "rows": rows,
            "base_date": base_date,
            "book_name": book_label(conn, book),
            "total_count": total_count,
            "sum_amount": sum_amount,
            "sort": sort,
            "dir": dir,
        },
    )


@router.get("/severance/{emp_id}", response_class=HTMLResponse)
async def severance_detail(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    emp = book_emp(conn, user["book"], emp_id)

    record = conn.execute(
        "SELECT * FROM severance_records WHERE employee_id=? ORDER BY id DESC LIMIT 1",
        (emp_id,),
    ).fetchone()
    record = dict(record) if record else None

    # 미지급 건은 열 때마다 최신 급여 데이터로 재계산해 severance_records에 반영함
    # 지급 완료/취소 건은 당시 지급액 기준. 재계산 제외
    basis = None
    tax = None
    if record and record["status"] == "pending":
        basis = calc_severance(conn, emp_id, resign_date=emp["resign_date"])
        if basis:
            tax = calc_sev_tax(basis["amount"], emp["hire_date"], emp["resign_date"])
            conn.execute(
                """UPDATE severance_records SET avg_salary=?, tenure_days=?, amount=?,
                   income_tax=?, local_tax=?, net_amount=? WHERE id=?""",
                (basis["avg_salary"], basis["tenure_days"], basis["amount"],
                 tax["income_tax"], tax["local_tax"], tax["net"], record["id"]),
            )
            conn.commit()
            record["avg_salary"] = basis["avg_salary"]
            record["tenure_days"] = basis["tenure_days"]
            record["amount"] = basis["amount"]
            record["income_tax"] = tax["income_tax"]
            record["local_tax"] = tax["local_tax"]
            record["net_amount"] = tax["net"]

    # 퇴사월 급여가 확정 상태면 연차수당 반영을 위해 확정 취소가 필요함
    resign_confirmed = False
    if emp["resign_date"]:
        rd = date.fromisoformat(emp["resign_date"])
        ps = conn.execute(
            "SELECT status FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
            (emp_id, rd.year, rd.month),
        ).fetchone()
        resign_confirmed = bool(ps and ps["status"] == "confirmed")

    return templates.TemplateResponse(
        request=request,
        name="hr/severance_detail.html",
        context={
            "request": request,
            "page_title": f"{emp['name']} - 퇴직금 내역",
            "user_name": user["name"],
            "user_role": user["role"],
            "employee": emp,
            "record": record,
            "basis": basis,
            "tax": tax,
            "resign_confirmed": resign_confirmed,
        },
    )


@router.post("/severance/{emp_id}/status", response_class=HTMLResponse)
async def severance_status_update(
    emp_id: int,
    status: str = Form(...),
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book_emp(conn, user["book"], emp_id)
    conn.execute(
        "UPDATE severance_records SET status=? WHERE employee_id=? ORDER BY id DESC LIMIT 1",
        (status, emp_id),
    )
    conn.commit()
    return RedirectResponse(url=f"/severance/{emp_id}", status_code=303)
