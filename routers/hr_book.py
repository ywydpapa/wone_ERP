import calendar
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from openpyxl.utils import get_column_letter

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.tz import now_kst
from core.deps import get_db, require_staff, templates
from core.books import INTERNAL, book_emp, book_label, emp_book, hr_book_ok, require_hr_book
from core.export import esc_cell, mask_rno, excel_response, HEADER_FONT, HEADER_FILL, CELL_FONT, THIN_BORDER
from core.payroll import (
    build_payslip, build_payslip_detail, calc_employer_insurance, calc_ordinary_hourly,
    calc_premium_pay, get_rates, is_five_plus,
)
from core.pay_items import get_items, PREMIUM_CODES
from core.attendance import is_month_closed, get_month_work_stats
from routers.erp_accounting import _create_payroll_slip

router = APIRouter()


@router.post("/hr-book")
async def set_hr_book(
    request: Request,
    book: int = Form(...),
    next: str = Form("/payroll"),
    u: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    if not next.startswith("/") or next.startswith("//"):
        next = "/payroll"
    request.session["hr_book"] = book if hr_book_ok(conn, u, book) else 0
    return RedirectResponse(url=next, status_code=303)


def _payroll_month(request):
    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
        month = int(request.query_params.get("month", now.month))
    except ValueError:
        year, month = now.year, now.month
    return year, month


def _prev_month(year, month):
    if month > 1:
        return year, month - 1
    return year - 1, 12


def _pay_date(conn, book, year, month):
    co = conn.execute("SELECT pay_day FROM client_companies WHERE id=?", (book,)).fetchone()
    pay_day = co["pay_day"] if co and co["pay_day"] else 25
    return f"{year}-{month:02d}-{pay_day:02d}"


# 급여 관리 (근로자별 명세 입력/확정)

@router.get("/payroll", response_class=HTMLResponse)
async def payroll_list(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    year, month = _payroll_month(request)
    book = user["book"]

    workers = conn.execute(
        "SELECT id, name, employee_no, dept, position FROM employees WHERE company_id IS ? AND status='active'",
        (emp_book(book),),
    ).fetchall()
    workers = [dict(w) for w in workers]

    for w in workers:
        ps = conn.execute(
            "SELECT status, gross_pay, total_deduction, net_pay FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
            (w["id"], year, month),
        ).fetchone()
        if ps:
            w["payslip_status"] = ps["status"]
            w["gross_pay"] = ps["gross_pay"]
            w["net_pay"] = ps["net_pay"]
            w["total_deduction"] = ps["total_deduction"]
        else:
            w["payslip_status"] = None

    has_draft = any(w["payslip_status"] == "draft" for w in workers)
    all_confirmed = all(w["payslip_status"] == "confirmed" for w in workers if w["payslip_status"])

    # 원 내부(book 0)는 근태 마감 대상이 아닌 wone 자체 서비스. 항상 마감된 것으로 취급
    att_closed = True if book == INTERNAL else is_month_closed(conn, year, month, book)

    pm = month - 1 if month > 1 else 12
    py_ = year if month > 1 else year - 1
    nm = month + 1 if month < 12 else 1
    ny = year if month < 12 else year + 1

    return templates.TemplateResponse(
        request=request, name="client/payroll.html", context={
            "request": request,
            "page_title": "급여 관리",
            "user_name": user["name"],
            "user_role": user["role"],
            "workers": workers,
            "year": year,
            "month": month,
            "book_name": book_label(conn, book),
            "has_draft": has_draft,
            "all_confirmed": all_confirmed,
            "att_closed": att_closed,
            "pm": pm, "py": py_, "nm": nm, "ny": ny,
            "error": request.query_params.get("error", ""),
        }
    )


# 급여대장

def _load_ledger(conn, year, month, book, filter_disabled=False):
    first_day = f"{year}-{month:02d}-01"
    _, last_d = calendar.monthrange(year, month)
    last_day = f"{year}-{month:02d}-{last_d:02d}"

    emp_sql = """
        SELECT e.id, e.name, e.employee_no, e.resident_no, e.hire_date, e.job_title,
               e.monthly_work_hours, e.disability_type, e.disability_grade,
               p.id AS payslip_id,
               p.gross_pay, p.national_pension, p.health_insurance,
               p.employment_insurance AS ei_deduction, p.income_tax, p.resident_tax,
               p.total_deduction, p.net_pay, p.status AS pay_status,
               p.employer_pension, p.employer_health, p.employer_employment, p.employer_accident
        FROM employees e
        LEFT JOIN payslips p ON e.id = p.employee_id AND p.pay_year=? AND p.pay_month=?
        WHERE e.status = 'active' AND e.company_id IS ?
    """
    params = [year, month, emp_book(book)]

    if filter_disabled:
        emp_sql += " AND e.disability_type IS NOT NULL AND e.disability_type != ''"

    emp_sql += " ORDER BY e.employee_no, e.name"
    rows = conn.execute(emp_sql, params).fetchall()
    rows = [dict(r) for r in rows]

    if not rows:
        return rows, {}

    payslip_ids = [r["payslip_id"] for r in rows if r["payslip_id"]]
    item_amounts = {}
    if payslip_ids:
        ph_p = ",".join("?" * len(payslip_ids))
        item_rows = conn.execute(
            f"""SELECT pi.payslip_id, it.code, pi.amount
                FROM payslip_items pi JOIN pay_items it ON it.id = pi.item_id
                WHERE pi.payslip_id IN ({ph_p})""",
            payslip_ids,
        ).fetchall()
        for r in item_rows:
            item_amounts.setdefault(r["payslip_id"], {})[r["code"]] = r["amount"]

    for r in rows:
        amounts = item_amounts.get(r["payslip_id"], {})
        r["base_salary"] = amounts.get("BASE", 0)
        r["overtime_pay"] = sum(amounts.get(c, 0) for c in ("OT", "NIGHT", "HOLIDAY"))
        r["disability_allowance"] = amounts.get("DISABLE", 0)
        r["meal_allowance"] = amounts.get("MEAL", 0)

    emp_ids = [r["id"] for r in rows]
    ph = ",".join("?" * len(emp_ids))
    att_rows = conn.execute(
        f"""SELECT employee_id,
                   COUNT(*) AS work_days,
                   SUM(work_minutes) AS total_work_mins,
                   SUM(overtime_minutes) AS total_ot_mins
            FROM attendance
            WHERE work_date BETWEEN ? AND ?
              AND status IN ('normal','late','early_leave','late_early')
              AND employee_id IN ({ph})
            GROUP BY employee_id""",
        [first_day, last_day, *emp_ids],
    ).fetchall()

    att_map = {r["employee_id"]: dict(r) for r in att_rows}
    return rows, att_map


@router.get("/payroll/ledger", response_class=HTMLResponse)
async def payroll_ledger(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    now = now_kst()
    year = int(request.query_params.get("year", now.year))
    month = int(request.query_params.get("month", now.month))
    filter_val = request.query_params.get("filter", "all")
    filter_disabled = filter_val == "disabled"
    book = user["book"]

    rows, att_map = _load_ledger(conn, year, month, book, filter_disabled)

    for r in rows:
        att = att_map.get(r["id"], {})
        r["work_days"] = att.get("work_days") or 0
        r["total_work_mins"] = att.get("total_work_mins") or 0
        r["total_ot_mins"] = att.get("total_ot_mins") or 0
        r["work_hours"] = r["total_work_mins"] // 60
        r["ot_hours"] = r["total_ot_mins"] // 60
        r["resident_no_masked"] = mask_rno(r.get("resident_no"))

    total_count = len(rows)
    sum_base = sum(r["base_salary"] or 0 for r in rows)
    sum_ot = sum(r["overtime_pay"] or 0 for r in rows)
    sum_dis = sum(r["disability_allowance"] or 0 for r in rows)
    sum_meal = sum(r["meal_allowance"] or 0 for r in rows)
    sum_gross = sum(r["gross_pay"] or 0 for r in rows)
    sum_pension = sum(r["national_pension"] or 0 for r in rows)
    sum_health = sum(r["health_insurance"] or 0 for r in rows)
    sum_ei = sum(r["ei_deduction"] or 0 for r in rows)
    sum_itax = sum(r["income_tax"] or 0 for r in rows)
    sum_rtax = sum(r["resident_tax"] or 0 for r in rows)
    sum_deduction = sum(r["total_deduction"] or 0 for r in rows)
    sum_net = sum(r["net_pay"] or 0 for r in rows)
    sum_er_pension = sum(r["employer_pension"] or 0 for r in rows)
    sum_er_health = sum(r["employer_health"] or 0 for r in rows)
    sum_er_employment = sum(r["employer_employment"] or 0 for r in rows)
    sum_er_accident = sum(r["employer_accident"] or 0 for r in rows)
    sum_er_total = sum_er_pension + sum_er_health + sum_er_employment + sum_er_accident

    return templates.TemplateResponse(
        request=request,
        name="hr/payroll_ledger.html",
        context={
            "request": request,
            "page_title": "급여대장",
            "user_name": user["name"],
            "user_role": user["role"],
            "rows": rows,
            "year": year,
            "month": month,
            "book_name": book_label(conn, book),
            "filter": filter_val,
            "total_count": total_count,
            "sum_base": sum_base,
            "sum_ot": sum_ot,
            "sum_dis": sum_dis,
            "sum_meal": sum_meal,
            "sum_gross": sum_gross,
            "sum_pension": sum_pension,
            "sum_health": sum_health,
            "sum_ei": sum_ei,
            "sum_itax": sum_itax,
            "sum_rtax": sum_rtax,
            "sum_deduction": sum_deduction,
            "sum_net": sum_net,
            "sum_er_pension": sum_er_pension,
            "sum_er_health": sum_er_health,
            "sum_er_employment": sum_er_employment,
            "sum_er_accident": sum_er_accident,
            "sum_er_total": sum_er_total,
        },
    )


@router.get("/payroll/ledger/export")
async def payroll_ledger_export(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    now = now_kst()
    year = int(request.query_params.get("year", now.year))
    month = int(request.query_params.get("month", now.month))
    filter_val = request.query_params.get("filter", "all")
    filter_disabled = filter_val == "disabled"
    book = user["book"]

    rows, att_map = _load_ledger(conn, year, month, book, filter_disabled)

    for r in rows:
        att = att_map.get(r["id"], {})
        r["work_days"] = att.get("work_days") or 0
        r["total_work_mins"] = att.get("total_work_mins") or 0
        r["total_ot_mins"] = att.get("total_ot_mins") or 0
        r["work_hours"] = r["total_work_mins"] // 60
        r["ot_hours"] = r["total_ot_mins"] // 60

    book_name = book_label(conn, book)

    wb = Workbook()
    ws = wb.active
    ws.title = "급여대장"

    title_text = f"급여대장 - {year}년 {month}월 ({book_name})"

    headers = [
        "순번", "근로자명", "주민등록번호", "고용연월일", "종사업무",
        "소정근로시간", "근로일수", "근로시간수", "연장근로시간",
        "기본급", "초과근무수당", "장애수당", "식대", "지급합계",
        "국민연금", "건강보험", "고용보험", "소득세", "지방소득세",
        "공제합계", "실지급액",
    ]

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    title_cell = ws.cell(row=1, column=1, value=title_text)
    title_cell.font = Font(name="맑은 고딕", bold=True, size=14)
    title_cell.alignment = Alignment(horizontal="center")

    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=2, column=ci, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER

    money_cols = set(range(10, len(headers) + 1))

    for ri, r in enumerate(rows, 3):
        vals = [
            ri - 2,
            esc_cell(r["name"]),
            esc_cell(mask_rno(r.get("resident_no"))),
            esc_cell(r.get("hire_date") or ""),
            esc_cell(r.get("job_title") or ""),
            r.get("monthly_work_hours") or 0,
            r["work_days"],
            r["work_hours"],
            r["ot_hours"],
            r.get("base_salary") or 0,
            r.get("overtime_pay") or 0,
            r.get("disability_allowance") or 0,
            r.get("meal_allowance") or 0,
            r.get("gross_pay") or 0,
            r.get("national_pension") or 0,
            r.get("health_insurance") or 0,
            r.get("ei_deduction") or 0,
            r.get("income_tax") or 0,
            r.get("resident_tax") or 0,
            r.get("total_deduction") or 0,
            r.get("net_pay") or 0,
        ]
        for ci, val in enumerate(vals, 1):
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font = CELL_FONT
            cell.border = THIN_BORDER
            if ci in money_cols and isinstance(val, (int, float)):
                cell.alignment = Alignment(horizontal="right")
                cell.number_format = "#,##0"
            else:
                cell.alignment = Alignment(horizontal="center")

    # 합계행
    sum_row = len(rows) + 3
    sum_vals = [
        "", "합계", "", "", "", "", "", "", "",
        sum(r.get("base_salary") or 0 for r in rows),
        sum(r.get("overtime_pay") or 0 for r in rows),
        sum(r.get("disability_allowance") or 0 for r in rows),
        sum(r.get("meal_allowance") or 0 for r in rows),
        sum(r.get("gross_pay") or 0 for r in rows),
        sum(r.get("national_pension") or 0 for r in rows),
        sum(r.get("health_insurance") or 0 for r in rows),
        sum(r.get("ei_deduction") or 0 for r in rows),
        sum(r.get("income_tax") or 0 for r in rows),
        sum(r.get("resident_tax") or 0 for r in rows),
        sum(r.get("total_deduction") or 0 for r in rows),
        sum(r.get("net_pay") or 0 for r in rows),
    ]
    for ci, val in enumerate(sum_vals, 1):
        cell = ws.cell(row=sum_row, column=ci, value=val)
        cell.font = HEADER_FONT
        cell.border = THIN_BORDER
        if ci in money_cols and isinstance(val, (int, float)):
            cell.alignment = Alignment(horizontal="right")
            cell.number_format = "#,##0"
        else:
            cell.alignment = Alignment(horizontal="center")

    col_widths = [6, 10, 16, 12, 12, 10, 8, 8, 8, 12, 12, 10, 10, 12, 10, 10, 10, 10, 10, 12, 12]
    for ci, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    filename = f"급여대장_{year}{month:02d}.xlsx"
    return excel_response(wb, filename)

def _item_rows_for_edit(conn, employee_id, book, year, month, worker, payslip):
    items = get_items(conn, book)
    five_plus = is_five_plus(conn, book)

    saved = {}
    if payslip:
        for r in conn.execute(
            "SELECT item_id, amount, overridden FROM payslip_items WHERE payslip_id=?", (payslip["id"],)
        ):
            saved[r["item_id"]] = {"amount": r["amount"], "overridden": bool(r["overridden"])}

    py, pm = _prev_month(year, month)
    prev_ps = conn.execute(
        "SELECT id FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
        (employee_id, py, pm),
    ).fetchone()
    prev_amounts = {}
    if prev_ps:
        for r in conn.execute(
            "SELECT item_id, amount FROM payslip_items WHERE payslip_id=?", (prev_ps["id"],)
        ):
            prev_amounts[r["item_id"]] = r["amount"]

    monthly_hours = worker.get("monthly_work_hours") or 0
    ordinary_total = 0
    for it in items:
        if not it["ordinary"]:
            continue
        if it["id"] in saved:
            ordinary_total += saved[it["id"]]["amount"]
        elif it["code"] == "BASE":
            ordinary_total += worker.get("base_salary") or 0
        else:
            ordinary_total += prev_amounts.get(it["id"], 0)
    hourly = calc_ordinary_hourly(ordinary_total, monthly_hours)

    stats = get_month_work_stats(conn, employee_id, f"{year}-{month:02d}")
    premium = calc_premium_pay(hourly, stats["ot_mins"], stats["night_mins"], stats["holiday_day_mins"], five_plus)

    rows = []
    for it in items:
        suggested = premium.get(it["code"]) if it["code"] in PREMIUM_CODES else None
        if it["id"] in saved:
            amount = saved[it["id"]]["amount"]
            overridden = saved[it["id"]]["overridden"]
        elif it["code"] == "BASE":
            amount = worker.get("base_salary") or 0
            overridden = False
        elif suggested is not None:
            amount = suggested
            overridden = False
        else:
            amount = prev_amounts.get(it["id"], 0)
            overridden = False
        rows.append({
            "item_id": it["id"], "code": it["code"], "name": it["name"],
            "amount": amount, "suggested": suggested, "overridden": overridden,
            "tax_free_limit": it["tax_free_limit"],
        })
    return rows, five_plus, stats


@router.get("/payroll/{emp_id}", response_class=HTMLResponse)
async def payroll_edit(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    year, month = _payroll_month(request)
    book = user["book"]
    worker = book_emp(conn, book, emp_id)

    payslip = conn.execute(
        "SELECT * FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
        (emp_id, year, month),
    ).fetchone()
    payslip = dict(payslip) if payslip else None

    is_locked = payslip and payslip.get("status") == "confirmed"

    item_rows, five_plus, stats = _item_rows_for_edit(conn, emp_id, book, year, month, worker, payslip)

    att_closed = True if book == INTERNAL else is_month_closed(conn, year, month, book)

    pm = month - 1 if month > 1 else 12
    py_ = year if month > 1 else year - 1
    nm = month + 1 if month < 12 else 1
    ny = year if month < 12 else year + 1

    return templates.TemplateResponse(
        request=request, name="client/payroll_edit.html", context={
            "request": request,
            "page_title": f"{worker['name']} 급여 입력",
            "user_name": user["name"],
            "worker": worker,
            "payslip": payslip,
            "item_rows": item_rows,
            "five_plus": five_plus,
            "year": year,
            "month": month,
            "is_locked": is_locked,
            "att_closed": att_closed,
            "pm": pm, "py": py_, "nm": nm, "ny": ny,
            "error": request.query_params.get("error", ""),
        }
    )


@router.post("/payroll/confirm")
async def payroll_confirm(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    form = await request.form()
    year = int(form.get("year", now_kst().year))
    month = int(form.get("month", now_kst().month))
    book = user["book"]

    # 원 내부(book 0)는 근태 마감 대상이 아닌 wone 자체 서비스. 마감 체크 생략
    if book != INTERNAL and not is_month_closed(conn, year, month, book):
        return RedirectResponse(
            url=f"/payroll?year={year}&month={month}&error=att_not_closed",
            status_code=303,
        )

    emp_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM employees WHERE company_id IS ? AND status='active'", (emp_book(book),)
    ).fetchall()]
    if emp_ids:
        placeholders = ",".join("?" * len(emp_ids))
        conn.execute(
            f"UPDATE payslips SET status='confirmed' WHERE employee_id IN ({placeholders}) AND pay_year=? AND pay_month=? AND status='draft'",
            (*emp_ids, year, month),
        )

        uid = user["id"]
        confirmed = conn.execute(
            f"""SELECT p.*, e.name as employee_name
                FROM payslips p JOIN employees e ON p.employee_id=e.id
                WHERE p.employee_id IN ({placeholders}) AND p.pay_year=? AND p.pay_month=? AND p.status='confirmed'""",
            (*emp_ids, year, month),
        ).fetchall()
        for ps in confirmed:
            ps = dict(ps)
            existing = conn.execute(
                "SELECT id FROM erp_docs WHERE payslip_id=?",
                (ps["id"],),
            ).fetchone()
            if not existing:
                try:
                    _create_payroll_slip(conn, book, ps, ps["employee_name"], uid)
                except ValueError as e:
                    conn.rollback()
                    return RedirectResponse(url=f"/payroll?year={year}&month={month}&error={quote(str(e))}", status_code=303)

        conn.commit()

    return RedirectResponse(url=f"/payroll?year={year}&month={month}", status_code=303)


def _save_payslip_items(conn, payslip_id, items, amounts, premium):
    conn.execute("DELETE FROM payslip_items WHERE payslip_id=?", (payslip_id,))
    for it in items:
        amount = amounts.get(it["id"], 0)
        if amount == 0 and it["code"] != "BASE":
            continue
        overridden = it["code"] in PREMIUM_CODES and amount != premium.get(it["code"])
        conn.execute(
            "INSERT INTO payslip_items (payslip_id, item_id, amount, overridden) VALUES (?,?,?,?)",
            (payslip_id, it["id"], amount, 1 if overridden else 0),
        )


@router.post("/payroll/bulk-generate")
async def payroll_bulk_generate(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
    year: int = Form(...),
    month: int = Form(...),
):
    book = user["book"]

    workers = conn.execute(
        """SELECT id, base_salary, monthly_work_hours, tax_dependent_count,
                  tax_child_count, tax_rate
           FROM employees
           WHERE company_id IS ? AND status='active'
             AND (resign_date IS NULL OR resign_date > ?)""",
        (emp_book(book), f"{year}-{month:02d}-01"),
    ).fetchall()

    pay_date = _pay_date(conn, book, year, month)
    rates = get_rates(conn, year, month)
    five_plus = is_five_plus(conn, book)
    items = get_items(conn, book)
    cnt = 0

    for w in workers:
        existing = conn.execute(
            "SELECT id FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
            (w["id"], year, month),
        ).fetchone()
        if existing:
            continue

        base = w["base_salary"] or 0
        monthly_hours = w["monthly_work_hours"] or 0
        hourly = calc_ordinary_hourly(base, monthly_hours)
        stats = get_month_work_stats(conn, w["id"], f"{year}-{month:02d}")
        premium = calc_premium_pay(hourly, stats["ot_mins"], stats["night_mins"], stats["holiday_day_mins"], five_plus)

        amounts = {}
        for it in items:
            if it["code"] == "BASE":
                amounts[it["id"]] = base
            elif it["code"] in premium:
                amounts[it["id"]] = premium[it["code"]]
            else:
                amounts[it["id"]] = 0

        build_items = [
            {"amount": amounts[it["id"]], "taxable": it["taxable"], "tax_free_limit": it["tax_free_limit"]}
            for it in items
        ]
        dependents = w["tax_dependent_count"] or 1
        children = w["tax_child_count"] or 0
        tax_rate = w["tax_rate"] or 100
        ps = build_payslip(build_items, rates, dependents, children, tax_rate)
        er = calc_employer_insurance(ps)
        premium_rule = "5인이상" if five_plus else "5인미만"

        cur = conn.execute("""
            INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, national_pension,
                health_insurance, long_care, employment_insurance, income_tax, resident_tax,
                total_deduction, net_pay, pay_date, status, created_at, premium_rule,
                employer_pension, employer_health, employer_employment, employer_accident)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'draft',datetime('now','localtime'),?,?,?,?,?)
        """, (w["id"], year, month, ps["gross_pay"], ps["national_pension"], ps["health_insurance"],
              ps["long_care"], ps["employment_insurance"], ps["income_tax"], ps["resident_tax"],
              ps["total_deduction"], ps["net_pay"], pay_date, premium_rule,
              er["employer_pension"], er["employer_health"], er["employer_employment"], er["employer_accident"]))
        _save_payslip_items(conn, cur.lastrowid, items, amounts, premium)
        cnt += 1

    conn.commit()

    return RedirectResponse(
        url=f"/payroll?year={year}&month={month}&bulk_done={cnt}",
        status_code=303,
    )


@router.post("/payroll/{emp_id}")
async def payroll_save(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
    year: int = Form(...),
    month: int = Form(...),
):
    book = user["book"]
    worker = book_emp(conn, book, emp_id)

    existing = conn.execute(
        "SELECT id, status FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
        (emp_id, year, month),
    ).fetchone()
    if existing and existing["status"] == "confirmed":
        return RedirectResponse(url=f"/payroll?year={year}&month={month}", status_code=303)

    items = get_items(conn, book)
    form = await request.form()
    amounts = {}
    for it in items:
        raw = form.get(f"amount_{it['id']}", "0")
        try:
            amt = int(raw)
        except ValueError:
            amt = 0
        if amt < 0:
            return RedirectResponse(
                url=f"/payroll/{emp_id}?year={year}&month={month}&error=negative",
                status_code=303,
            )
        amounts[it["id"]] = amt

    five_plus = is_five_plus(conn, book)
    ordinary_total = sum(amounts[it["id"]] for it in items if it["ordinary"])
    hourly = calc_ordinary_hourly(ordinary_total, worker["monthly_work_hours"] or 0)
    stats = get_month_work_stats(conn, emp_id, f"{year}-{month:02d}")
    premium = calc_premium_pay(hourly, stats["ot_mins"], stats["night_mins"], stats["holiday_day_mins"], five_plus)

    build_items = [
        {"amount": amounts[it["id"]], "taxable": it["taxable"], "tax_free_limit": it["tax_free_limit"]}
        for it in items
    ]
    dependents = worker["tax_dependent_count"] or 1
    children = worker["tax_child_count"] or 0
    tax_rate = worker["tax_rate"] or 100
    rates = get_rates(conn, year, month)
    ps = build_payslip(build_items, rates, dependents, children, tax_rate)
    er = calc_employer_insurance(ps)
    pay_date = _pay_date(conn, book, year, month)
    premium_rule = "5인이상" if five_plus else "5인미만"

    if existing:
        payslip_id = existing["id"]
        conn.execute("""
            UPDATE payslips SET gross_pay=?, national_pension=?, health_insurance=?,
                long_care=?, employment_insurance=?, income_tax=?, resident_tax=?,
                total_deduction=?, net_pay=?, pay_date=?, status='draft', premium_rule=?,
                employer_pension=?, employer_health=?, employer_employment=?, employer_accident=?
            WHERE id=?
        """, (ps["gross_pay"], ps["national_pension"], ps["health_insurance"], ps["long_care"],
              ps["employment_insurance"], ps["income_tax"], ps["resident_tax"], ps["total_deduction"],
              ps["net_pay"], pay_date, premium_rule,
              er["employer_pension"], er["employer_health"], er["employer_employment"], er["employer_accident"],
              payslip_id))
    else:
        cur = conn.execute("""
            INSERT INTO payslips (employee_id, pay_year, pay_month, gross_pay, national_pension,
                health_insurance, long_care, employment_insurance, income_tax, resident_tax,
                total_deduction, net_pay, pay_date, status, created_at, premium_rule,
                employer_pension, employer_health, employer_employment, employer_accident)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'draft',datetime('now','localtime'),?,?,?,?,?)
        """, (emp_id, year, month, ps["gross_pay"], ps["national_pension"], ps["health_insurance"],
              ps["long_care"], ps["employment_insurance"], ps["income_tax"], ps["resident_tax"],
              ps["total_deduction"], ps["net_pay"], pay_date, premium_rule,
              er["employer_pension"], er["employer_health"], er["employer_employment"], er["employer_accident"]))
        payslip_id = cur.lastrowid

    _save_payslip_items(conn, payslip_id, items, amounts, premium)
    conn.commit()

    return RedirectResponse(url=f"/payroll?year={year}&month={month}", status_code=303)


@router.get("/payroll/{emp_id}/print", response_class=HTMLResponse)
async def payslip_print(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    now = now_kst()
    book = user["book"]
    worker = book_emp(conn, book, emp_id)
    try:
        year = int(request.query_params.get("year", now.year))
        month = int(request.query_params.get("month", now.month))
    except ValueError:
        return RedirectResponse(url="/payroll/ledger", status_code=303)

    row = conn.execute(
        "SELECT * FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=?",
        (emp_id, year, month),
    ).fetchone()
    if not row:
        return RedirectResponse(url="/payroll/ledger", status_code=303)

    payslip = dict(row)
    work_stats, calc_notes, items = build_payslip_detail(
        conn, emp_id, worker.get("monthly_work_hours") or 0, payslip
    )

    return templates.TemplateResponse(
        request=request, name="hr/payslip_print.html", context={
            "payslip": payslip,
            "employee": worker,
            "company_name": book_label(conn, book),
            "work_stats": work_stats,
            "calc_notes": calc_notes,
            "items": items,
        }
    )


# 급여 마스터 정보 (사원 화면에서 분리된 지급 기준값)

@router.get("/payroll/{emp_id}/info", response_class=HTMLResponse)
async def payroll_info_form(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    worker = book_emp(conn, user["book"], emp_id)
    return templates.TemplateResponse(
        request=request, name="client/payroll_info.html", context={
            "request": request,
            "page_title": f"{worker['name']} - 급여 마스터 정보",
            "user_name": user["name"],
            "worker": worker,
            "error": "",
        }
    )


@router.post("/payroll/{emp_id}/info", response_class=HTMLResponse)
async def payroll_info_save(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
    base_salary: int = Form(0),
    monthly_work_hours: int = Form(0),
    employment_insurance: int = Form(1),
    tax_dependent_count: int = Form(1),
    tax_child_count: int = Form(0),
    tax_rate: int = Form(100),
    bank_name: str = Form(""),
    bank_account: str = Form(""),
):
    worker = book_emp(conn, user["book"], emp_id)
    if tax_rate not in (80, 100, 120):
        return templates.TemplateResponse(
            request=request, name="client/payroll_info.html", context={
                "request": request,
                "page_title": f"{worker['name']} - 급여 마스터 정보",
                "user_name": user["name"],
                "worker": worker,
                "error": "원천징수 비율은 80/100/120 중 하나여야 합니다",
            }
        )
    conn.execute(
        """UPDATE employees SET base_salary=?, monthly_work_hours=?, employment_insurance=?,
               tax_dependent_count=?, tax_child_count=?, tax_rate=?, bank_name=?, bank_account=?,
               updated_at=datetime('now','localtime')
           WHERE id=?""",
        (base_salary, monthly_work_hours, employment_insurance, max(1, tax_dependent_count),
         max(0, tax_child_count), tax_rate, bank_name, bank_account, emp_id),
    )
    conn.commit()
    return RedirectResponse(url=f"/payroll/{emp_id}/info", status_code=303)



