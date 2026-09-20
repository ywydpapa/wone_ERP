from core.tz import now_kst

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from core.deps import get_db, require_login, templates
from core.constants import DISABILITY_DEGREE_LABELS
from core.export import styled_workbook, excel_response

router = APIRouter()


def _fetch_employees(conn, company_id, status_filter):
    sql = (
        "SELECT e.id, e.name, e.employee_no, e.resident_no, "
        "e.disability_type, e.disability_grade, "
        "e.hire_date, e.monthly_work_hours, e.employment_insurance, "
        "cc.name AS company_name "
        "FROM employees e "
        "LEFT JOIN client_companies cc ON e.company_id = cc.id "
        "WHERE 1=1"
    )
    params = []

    if status_filter == "active":
        sql += " AND e.status = 'active'"
    elif status_filter == "retired":
        sql += " AND e.status = 'retired'"

    if company_id:
        sql += " AND e.company_id = ?"
        params.append(company_id)

    sql += " ORDER BY e.company_id, e.employee_no, e.name"
    return conn.execute(sql, params).fetchall()


def _build_rows(raw, degree_filter):
    rows = []
    for r in raw:
        d = dict(r)
        grade = d.get("disability_grade") or ""
        hours = d.get("monthly_work_hours") or 0

        if degree_filter and grade != degree_filter:
            continue

        d["heavy2x"] = (grade == "심한장애" and hours >= 60)
        rn = d.get("resident_no") or ""
        if len(rn) >= 14:
            d["resident_no_masked"] = rn[:6] + "-" + "*" * 7
        elif rn:
            d["resident_no_masked"] = rn[:6] + "-*******"
        else:
            d["resident_no_masked"] = "-"
        rows.append(d)
    return rows


@router.get("/worker-roster", response_class=HTMLResponse)
async def worker_roster(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    now = now_kst()
    year = int(request.query_params.get("year", now.year))
    company_id = request.query_params.get("company_id", "")
    company_id = int(company_id) if company_id else None
    status_filter = request.query_params.get("status_filter", "active")
    degree_filter = request.query_params.get("degree_filter", "")

    raw = _fetch_employees(conn, company_id, status_filter)
    rows = _build_rows(raw, degree_filter)

    companies = conn.execute(
        "SELECT id, name FROM client_companies WHERE status='active' ORDER BY name"
    ).fetchall()

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
            "user_role": user["role"],
            "rows": rows,
            "stats": stats,
            "year": year,
            "company_id": company_id or "",
            "status_filter": status_filter,
            "degree_filter": degree_filter,
            "companies": companies,
            "degree_labels": DISABILITY_DEGREE_LABELS,
        },
    )


@router.get("/worker-roster/export")
async def worker_roster_export(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    now = now_kst()
    year = int(request.query_params.get("year", now.year))
    company_id = request.query_params.get("company_id", "")
    company_id = int(company_id) if company_id else None

    raw = _fetch_employees(conn, company_id, status_filter="")
    rows = _build_rows(raw, degree_filter="")

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

    company_name = ""
    if company_id:
        row = conn.execute(
            "SELECT name FROM client_companies WHERE id=?", (company_id,)
        ).fetchone()
        if row:
            company_name = row["name"]

    headers = [
        "순번", "성명", "주민등록번호", "장애유형", "장애정도",
        "고용일", "월소정근로시간", "월임금", "고용보험가입여부",
    ]

    data_rows = []
    for i, r in enumerate(rows, 1):
        rn = r.get("resident_no") or ""
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

    filename = f"장애인근로자명부_{year}"
    if company_name:
        filename += f"_{company_name}"
    filename += ".xlsx"

    return excel_response(wb, filename)
