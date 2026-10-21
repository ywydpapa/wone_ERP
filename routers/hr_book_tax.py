import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from core.tz import now_kst, today_kst
from core.deps import get_db, templates
from core.books import INTERNAL, book_emp, book_label, company_info, emp_book, require_hr_book
from core.constants import DISABILITY_DEGREE_LABELS
from core.export import esc_cell, mask_rno, styled_workbook, excel_response
from core.crypto import dec_rno
from core import audit
from core.withholding import (
    get_employee_yearly, get_report, get_simple_statement, get_simple_statement_month,
    simple_monthly, taxable_by_payslip,
)

router = APIRouter()


# 원천징수이행상황신고서 / 간이지급명세서

def _target_period(request):
    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
        month = int(request.query_params.get("month", now.month))
    except ValueError:
        year, month = now.year, now.month
    return year, month


@router.get("/withholding", response_class=HTMLResponse)
async def withholding_report(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book = user["book"]
    year, month = _target_period(request)
    report = get_report(conn, emp_book(book), year, month)
    for r in report["rows"]:
        r["resident_no_masked"] = mask_rno(r.get("resident_no"))
    return templates.TemplateResponse(
        request=request, name="hr/withholding_report.html", context={
            "request": request,
            "page_title": "원천징수이행상황신고서",
            "user_name": user["name"],
            "report": report,
            "year": year,
            "month": month,
            "book_name": book_label(conn, book),
            "company": _company_row(conn, book),
            "base_url": "/withholding",
        }
    )


def _export_csv(report, filename):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["사번", "성명", "주민등록번호", "귀속연월", "지급연월", "과세", "제출비과세", "총지급액", "소득세", "지방소득세"])
    for r in report["rows"]:
        w.writerow([esc_cell(v) for v in [
            r.get("employee_no") or "", r["emp_name"], mask_rno(r["resident_no"]),
            f"{r['pay_year']}-{r['pay_month']:02d}", r.get("pay_date") or "",
            r["taxable_pay"], r["submit_free_pay"], r["total_pay"], r["income_tax"] or 0, r["resident_tax"] or 0,
        ]])
    w.writerow([])
    w.writerow(["합계", "", "", "", "", "", "", report["sum_pay"], report["sum_tax"], report["sum_resident"]])
    buf.seek(0)
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/withholding/export")
async def withholding_export(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
    reason: str = Depends(audit.require_reason),
):
    year, month = _target_period(request)
    report = get_report(conn, emp_book(user["book"]), year, month)
    audit.log_pii_export(conn, user, request, reason, "원천징수이행상황신고서 CSV",
                          len(report["rows"]), company_id=user["book"] or None)
    return _export_csv(report, f"withholding_{year}{month:02d}.csv")


@router.get("/withholding/employees/{emp_id}", response_class=HTMLResponse)
async def withholding_employee(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book = user["book"]
    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
    except ValueError:
        year = now.year

    emp = book_emp(conn, book, emp_id)
    emp["resident_no_masked"] = mask_rno(dec_rno(emp.pop("resident_no")))

    record = get_employee_yearly(conn, emp_id, year)

    return templates.TemplateResponse(
        request=request, name="hr/withholding_employee.html", context={
            "request": request,
            "page_title": "근로소득 원천징수부",
            "user_name": user["name"],
            "employee": emp,
            "company": _company_row(conn, book),
            "record": record,
            "year": year,
            "base_url": f"/withholding/employees/{emp_id}",
        }
    )


def _company_row(conn, book):
    if book == INTERNAL:
        info = company_info(conn, book)
        return {"name": info["name"], "business_no": info["biz_no"],
                "representative": info["representative"], "address": info["address"]}
    row = conn.execute(
        "SELECT name, business_no, representative, address FROM client_companies WHERE id=?", (book,)
    ).fetchone()
    return dict(row) if row else {}


@router.get("/withholding/simple-statement", response_class=HTMLResponse)
async def simple_statement(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book = user["book"]
    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
    except ValueError:
        year = now.year
    monthly = simple_monthly(year)
    half = 2 if request.query_params.get("half") == "2" else 1
    month = max(1, min(12, int(request.query_params.get("month", now.month) or now.month)))

    if monthly:
        stmt = get_simple_statement_month(conn, emp_book(book), year, month)
    else:
        stmt = get_simple_statement(conn, emp_book(book), year, half)
    for r in stmt["rows"]:
        r["resident_no_masked"] = mask_rno(r.get("resident_no"))

    return templates.TemplateResponse(
        request=request, name="hr/withholding_simple.html", context={
            "request": request,
            "page_title": "간이지급명세서(근로소득)",
            "user_name": user["name"],
            "stmt": stmt,
            "year": year,
            "half": half,
            "month": month,
            "monthly": monthly,
            "company": _company_row(conn, book),
            "book_name": book_label(conn, book),
            "base_url": "/withholding/simple-statement",
        }
    )


def _export_simple_csv(stmt, filename):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["성명", "주민등록번호", "내외국인", "거주지국", "근무시작일", "근무종료일", "과세 급여등", "인정상여"])
    for r in stmt["rows"]:
        w.writerow([esc_cell(v) for v in [
            r["name"], r["resident_no"] or "", "1", "KR", r["work_start"], r["work_end"], r["taxable_total"], 0,
        ]])
    buf.seek(0)
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/withholding/simple-statement/export")
async def simple_statement_export(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
    reason: str = Depends(audit.require_reason),
):
    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
    except ValueError:
        year = now.year
    if simple_monthly(year):
        month = max(1, min(12, int(request.query_params.get("month", now.month) or now.month)))
        stmt = get_simple_statement_month(conn, emp_book(user["book"]), year, month)
        audit.log_pii_export(conn, user, request, reason, "간이지급명세서 CSV",
                              len(stmt["rows"]), company_id=user["book"] or None)
        return _export_simple_csv(stmt, f"simple_statement_{year}{month:02d}.csv")
    half = 2 if request.query_params.get("half") == "2" else 1
    stmt = get_simple_statement(conn, emp_book(user["book"]), year, half)
    audit.log_pii_export(conn, user, request, reason, "간이지급명세서 CSV",
                          len(stmt["rows"]), company_id=user["book"] or None)
    return _export_simple_csv(stmt, f"simple_statement_{year}_{half}half.csv")


# 4대보험 취득/상실 신고

EI_LOSS_CODES = {
    "11": "개인사정 자진퇴사",
    "23": "경영상 필요/권고사직",
    "26": "근로자 귀책 징계해고",
    "31": "정년",
    "32": "계약기간 만료",
    "41": "기타",
}

HI_LOSS_CODE, HI_LOSS_LABEL = "01", "퇴직"
NP_LOSS_CODE, NP_LOSS_LABEL = "3", "사용관계종료"


def _match_ei_loss_code(reason):
    # 권고사직이 사직으로 잡히지 않도록 구체 사유 우선 매칭
    reason = reason or ""
    if "권고" in reason or "경영" in reason:
        return "23", False
    if "징계" in reason or "해고" in reason:
        return "26", False
    if "정년" in reason:
        return "31", False
    if "계약" in reason or "만료" in reason:
        return "32", False
    if "사직" in reason or "자진" in reason:
        return "11", False
    return "11", True


def _deadline_15th(base_date):
    y, m = base_date.year, base_date.month
    if m == 12:
        y, m = y + 1, 1
    else:
        m += 1
    return date(y, m, 15)


def _default_period():
    now = now_kst()
    first = date(now.year, now.month, 1)
    nxt = date(now.year + 1, 1, 1) if now.month == 12 else date(now.year, now.month + 1, 1)
    last = nxt - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def _std_work_hours(monthly_work_hours):
    hours = monthly_work_hours or 0
    if not hours:
        return 40
    return round(hours / 4.345) - 8


def _monthly_income(conn, emp):
    row = conn.execute(
        """SELECT id FROM payslips WHERE employee_id = ? AND status = 'confirmed'
           ORDER BY pay_year, pay_month LIMIT 1""",
        (emp["id"],),
    ).fetchone()
    if row:
        return taxable_by_payslip(conn, [row["id"]])[row["id"]]
    return emp.get("base_salary") or 0


def _year_taxable_sum(conn, emp_id, year, upto_month=None):
    sql = "SELECT id FROM payslips WHERE employee_id=? AND status='confirmed' AND pay_year=?"
    params = [emp_id, year]
    if upto_month:
        sql += " AND pay_month<=?"
        params.append(upto_month)
    ids = [r["id"] for r in conn.execute(sql, params).fetchall()]
    return sum(taxable_by_payslip(conn, ids).values())


def _fetch_employees(conn, book, col, date_from, date_to):
    rows = conn.execute(
        f"SELECT * FROM employees WHERE company_id IS ? AND {col} BETWEEN ? AND ? ORDER BY {col}, name",
        (emp_book(book), date_from, date_to),
    ).fetchall()
    return [dict(r) for r in rows]


def _build_acq_rows(conn, book, date_from, date_to):
    today = today_kst()
    rows = []
    for e in _fetch_employees(conn, book, "hire_date", date_from, date_to):
        hire = date.fromisoformat(e["hire_date"])
        deadline = _deadline_15th(hire)
        rno = dec_rno(e.get("resident_no"))
        rows.append({
            "name": e["name"],
            "resident_no": rno or "",
            "resident_no_masked": mask_rno(rno),
            "acq_date": e["hire_date"],
            "monthly_income": _monthly_income(conn, e),
            "std_hours": _std_work_hours(e.get("monthly_work_hours")),
            "ei_joined": bool(e.get("employment_insurance")),
            "disabled": bool(e.get("disability_type")),
            "deadline": deadline.isoformat(),
            "overdue": today > deadline,
        })
    return rows


def _build_loss_rows(conn, book, date_from, date_to):
    today = today_kst()
    rows = []
    for e in _fetch_employees(conn, book, "resign_date", date_from, date_to):
        resign = date.fromisoformat(e["resign_date"])
        loss_date = resign + timedelta(days=1)
        deadline = _deadline_15th(loss_date)
        ei_code, need_confirm = _match_ei_loss_code(e.get("resign_reason"))
        rno = dec_rno(e.get("resident_no"))
        rows.append({
            "name": e["name"],
            "resident_no": rno or "",
            "resident_no_masked": mask_rno(rno),
            "resign_date": e["resign_date"],
            "loss_date": loss_date.isoformat(),
            "ei_code": ei_code,
            "ei_label": EI_LOSS_CODES[ei_code],
            "need_confirm": need_confirm,
            "hi_code": HI_LOSS_CODE,
            "hi_label": HI_LOSS_LABEL,
            "np_code": NP_LOSS_CODE,
            "np_label": NP_LOSS_LABEL,
            "cur_year_pay": _year_taxable_sum(conn, e["id"], resign.year, resign.month),
            "prev_year_pay": _year_taxable_sum(conn, e["id"], resign.year - 1),
            "deadline": deadline.isoformat(),
            "overdue": today > deadline,
        })
    return rows


def _build_rows(conn, book, kind, date_from, date_to):
    if kind == "loss":
        return _build_loss_rows(conn, book, date_from, date_to)
    return _build_acq_rows(conn, book, date_from, date_to)


def _query_period(request):
    default_from, default_to = _default_period()
    date_from = request.query_params.get("from") or default_from
    date_to = request.query_params.get("to") or default_to
    kind = request.query_params.get("kind", "acq")
    if kind not in ("acq", "loss"):
        kind = "acq"
    return date_from, date_to, kind


def _insurance_csv_response(rows, kind, date_from, date_to):
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)

    if kind == "loss":
        writer.writerow([
            "성명", "주민등록번호", "퇴사일", "자격상실일",
            "고용보험상실사유코드", "고용보험상실사유", "확인필요",
            "건강보험상실부호", "국민연금상실부호",
            "당해연도보수총액", "전년도보수총액", "신고기한", "기한초과",
        ])
        for r in rows:
            writer.writerow([esc_cell(v) for v in [
                r["name"], r["resident_no"], r["resign_date"], r["loss_date"],
                r["ei_code"], r["ei_label"], "Y" if r["need_confirm"] else "",
                r["hi_code"], r["np_code"],
                r["cur_year_pay"], r["prev_year_pay"], r["deadline"],
                "Y" if r["overdue"] else "",
            ]])
        filename = f"insurance_loss_{date_from}_{date_to}.csv"
    else:
        writer.writerow([
            "성명", "주민등록번호", "자격취득일", "월소득액(보수월액)",
            "주소정근로시간", "고용보험가입여부", "장애인여부", "신고기한", "기한초과",
        ])
        for r in rows:
            writer.writerow([esc_cell(v) for v in [
                r["name"], r["resident_no"], r["acq_date"], r["monthly_income"],
                r["std_hours"], "가입" if r["ei_joined"] else "미가입",
                "Y" if r["disabled"] else "", r["deadline"],
                "Y" if r["overdue"] else "",
            ]])
        filename = f"insurance_acq_{date_from}_{date_to}.csv"

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/insurance-reports", response_class=HTMLResponse)
async def insurance_reports(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book = user["book"]
    date_from, date_to, kind = _query_period(request)
    rows = _build_rows(conn, book, kind, date_from, date_to)

    return templates.TemplateResponse(
        request=request,
        name="hr/insurance_report.html",
        context={
            "request": request,
            "page_title": "4대보험 취득/상실 신고",
            "user_name": user["name"],
            "base_url": "/insurance-reports",
            "book_name": book_label(conn, book),
            "rows": rows,
            "kind": kind,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@router.get("/insurance-reports/export")
async def insurance_reports_export(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
    reason: str = Depends(audit.require_reason),
):
    date_from, date_to, kind = _query_period(request)
    rows = _build_rows(conn, user["book"], kind, date_from, date_to)
    audit.log_pii_export(conn, user, request, reason, "4대보험 취득상실 신고 CSV",
                          len(rows), company_id=user["book"] or None)
    return _insurance_csv_response(rows, kind, date_from, date_to)


# 장애인 근로자 명부

def _fetch_roster_employees(conn, book, status_filter):
    sql = (
        "SELECT e.id, e.name, e.employee_no, e.resident_no, "
        "e.disability_type, e.disability_grade, "
        "e.hire_date, e.monthly_work_hours, e.employment_insurance "
        "FROM employees e "
        "WHERE e.company_id IS ?"
    )
    params = [emp_book(book)]

    if status_filter == "active":
        sql += " AND e.status = 'active'"
    elif status_filter == "retired":
        sql += " AND e.status = 'retired'"

    sql += " ORDER BY e.employee_no, e.name"
    return conn.execute(sql, params).fetchall()


def _build_roster_rows(raw, degree_filter):
    rows = []
    for r in raw:
        d = dict(r)
        grade = d.get("disability_grade") or ""
        hours = d.get("monthly_work_hours") or 0

        if degree_filter and grade != degree_filter:
            continue

        d["heavy2x"] = (grade == "심한장애" and hours >= 60)
        d["resident_no_masked"] = mask_rno(dec_rno(d.pop("resident_no")) or "")
        rows.append(d)
    return rows


@router.get("/roster", response_class=HTMLResponse)
async def worker_roster(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    now = now_kst()
    year = int(request.query_params.get("year", now.year))
    status_filter = request.query_params.get("status_filter", "active")
    degree_filter = request.query_params.get("degree_filter", "")
    book = user["book"]

    raw = _fetch_roster_employees(conn, book, status_filter)
    rows = _build_roster_rows(raw, degree_filter)

    total = len(rows)
    heavy_cnt = sum(1 for r in rows if r.get("disability_grade") == "심한장애")
    mild_cnt = sum(1 for r in rows if r.get("disability_grade") == "심하지않은장애")
    heavy2x_cnt = sum(1 for r in rows if r.get("heavy2x"))

    stats = {
        "total": total,
        "heavy": heavy_cnt,
        "mild": mild_cnt,
        "heavy2x": heavy2x_cnt,
    }

    return templates.TemplateResponse(
        request=request,
        name="hr/worker_roster.html",
        context={
            "request": request,
            "page_title": "장애인 근로자 명부",
            "user_name": user["name"],
            "rows": rows,
            "stats": stats,
            "year": year,
            "book_name": book_label(conn, book),
            "status_filter": status_filter,
            "degree_filter": degree_filter,
            "degree_labels": DISABILITY_DEGREE_LABELS,
        },
    )


@router.get("/roster/export")
async def worker_roster_export(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
    reason: str = Depends(audit.require_reason),
):
    now = now_kst()
    year = int(request.query_params.get("year", now.year))
    book = user["book"]

    raw = _fetch_roster_employees(conn, book, status_filter="")
    rows = _build_roster_rows(raw, degree_filter="")

    # 해당 연도 최신 급여명세 조회
    emp_ids = [r["id"] for r in rows]
    wage_map = {}
    if emp_ids:
        ph = ",".join("?" * len(emp_ids))
        slips = conn.execute(
            f"""SELECT employee_id, gross_pay
                FROM payslips
                WHERE employee_id IN ({ph}) AND pay_year = ?
                ORDER BY pay_month DESC""",
            [*emp_ids, year],
        ).fetchall()
        for s in slips:
            if s["employee_id"] not in wage_map:
                wage_map[s["employee_id"]] = s["gross_pay"] or 0

    headers = [
        "순번", "성명", "주민등록번호", "장애유형", "장애정도",
        "고용일", "월소정근로시간", "월임금", "고용보험가입여부",
    ]

    data_rows = []
    for i, r in enumerate(rows, 1):
        rn = r.get("resident_no_masked") or ""
        grade = r.get("disability_grade") or ""
        grade_label = DISABILITY_DEGREE_LABELS.get(grade, grade)
        ins = "가입" if r.get("employment_insurance") else "미가입"
        wage = wage_map.get(r["id"], 0)
        data_rows.append([
            i,
            r["name"],
            rn,
            r.get("disability_type") or "",
            grade_label,
            r.get("hire_date") or "",
            r.get("monthly_work_hours") or 0,
            wage,
            ins,
        ])

    col_widths = [6, 10, 16, 12, 14, 12, 14, 12, 12]
    wb = styled_workbook("장애인근로자명부", headers, data_rows, col_widths)

    filename = f"장애인근로자명부_{year}_{book_label(conn, book)}.xlsx"

    audit.log_pii_export(conn, user, request, reason, "장애인 근로자명부 엑셀", len(data_rows), company_id=book or None)
    return excel_response(wb, filename)


# 근로자명부 (근로기준법 시행규칙 별지 제16호서식)

def _register_rows(conn, book, status_filter):
    sql = "SELECT * FROM employees WHERE company_id IS ?"
    params = [emp_book(book)]

    if status_filter == "active":
        sql += " AND status = 'active'"
    elif status_filter == "retired":
        sql += " AND status = 'retired'"

    sql += " ORDER BY employee_no, name"
    return conn.execute(sql, params).fetchall()


@router.get("/register", response_class=HTMLResponse)
async def worker_register(
    request: Request,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book = user["book"]
    status_filter = request.query_params.get("status_filter", "active")
    rows = _register_rows(conn, book, status_filter)

    return templates.TemplateResponse(
        request=request,
        name="hr/worker_register.html",
        context={
            "request": request,
            "page_title": "근로자명부",
            "user_name": user["name"],
            "rows": rows,
            "book_name": book_label(conn, book),
            "status_filter": status_filter,
        },
    )


@router.get("/register/{emp_id}/print", response_class=HTMLResponse)
async def worker_register_print(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
    reason: str = Depends(audit.require_reason),
):
    emp = book_emp(conn, user["book"], emp_id)
    audit.log_pii_export(conn, user, request, reason, "근로자명부 인쇄", 1,
                          company_id=user["book"] or None, action="print")
    return templates.TemplateResponse(
        request=request,
        name="hr/worker_register_print.html",
        context={
            "request": request,
            "emp": emp,
            "company": company_info(conn, user["book"]),
            "viewer_name": user["name"],
            "viewed_at": now_kst().strftime("%Y-%m-%d %H:%M"),
        },
    )


