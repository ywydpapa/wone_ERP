from core.tz import now_kst

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from core.deps import get_db, require_login, require_staff, templates
from routers._helpers import get_page
from core.capability import derive_tier2, derive_tier3
from core.attendance import (
    get_attendance_records,
    get_attendance_summary,
    get_worker_detail,
    get_worker_month_records,
    build_calendar_data,
    worker_month_summary,
    prev_next_month,
    available_months,
)

router = APIRouter(prefix="/hr")


@router.get("/employees", response_class=HTMLResponse)
async def employee_list(
    request: Request,
    q: str = "",
    dept: str = "",
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    page = get_page(request)
    per_page = 10
    base_sql = (
        "FROM employees e "
        "LEFT JOIN client_companies cc ON e.company_id = cc.id "
        "WHERE 1=1"
    )
    params = []
    if q:
        base_sql += " AND e.name LIKE ?"
        params.append(f"%{q}%")
    if dept:
        base_sql += " AND e.dept = ?"
        params.append(dept)
    total = conn.execute("SELECT COUNT(*) " + base_sql, params).fetchone()[0]
    sql = "SELECT e.*, cc.name AS company_name " + base_sql + " ORDER BY e.employee_no LIMIT ? OFFSET ?"
    employees = conn.execute(sql, params + [per_page, (page - 1) * per_page]).fetchall()
    depts = conn.execute(
        "SELECT DISTINCT dept FROM employees ORDER BY dept"
    ).fetchall()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request=request,
        name="hr/employee_list.html",
        context={
            "request": request,
            "page_title": "인사관리 - 직원 목록",
            "user_name": user["user_name"],
            "user_role": user["user_role"],
            "employees": employees,
            "depts": [r["dept"] for r in depts],
            "q": q,
            "selected_dept": dept,
            "total_count": total,
            "page": page,
            "total_pages": total_pages,
            "base_url": f"/hr/employees?q={q}&dept={dept}&",
        },
    )


@router.get("/employees/new", response_class=HTMLResponse)
async def employee_new(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    companies = conn.execute(
        "SELECT id, name FROM client_companies WHERE status='active' ORDER BY name"
    ).fetchall()
    return templates.TemplateResponse(
        request=request,
        name="hr/employee_form.html",
        context={
            "request": request,
            "page_title": "직원 신규 등록",
            "user_name": user["user_name"],
            "user_role": user["user_role"],
            "employee": None,
            "companies": companies,
            "error": "",
        },
    )


@router.post("/employees", response_class=HTMLResponse)
async def employee_create(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
    name: str = Form(...),
    employee_no: str = Form(""),
    dept: str = Form("경영지원팀"),
    position: str = Form("사원"),
    hire_date: str = Form(""),
    status: str = Form("active"),
    disability_type: str = Form(""),
    disability_grade: str = Form(""),
    emergency_contact: str = Form(""),
    emergency_phone: str = Form(""),
    notes: str = Form(""),
    company_id: str = Form(""),
):
    try:
        cur = conn.execute(
            """INSERT INTO employees
               (name, employee_no, dept, position, hire_date, status,
                disability_type, disability_grade,
                emergency_contact, emergency_phone, notes, company_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, employee_no or None, dept, position, hire_date, status,
             disability_type, disability_grade,
             emergency_contact, emergency_phone, notes,
             int(company_id) if company_id else None),
        )
        conn.commit()
        new_id = cur.lastrowid
    except Exception:
        companies = conn.execute(
            "SELECT id, name FROM client_companies WHERE status='active' ORDER BY name"
        ).fetchall()
        return templates.TemplateResponse(
            request=request,
            name="hr/employee_form.html",
            context={
                "request": request,
                "page_title": "직원 신규 등록",
                "user_name": user["user_name"],
                "user_role": user["user_role"],
                "employee": None,
                "companies": companies,
                "error": "사번이 중복되었거나 필수 항목이 누락되었습니다.",
            },
        )
    return RedirectResponse(url=f"/hr/employees/{new_id}", status_code=303)


@router.get("/employees/{emp_id}", response_class=HTMLResponse)
async def employee_detail(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    employee = conn.execute(
        "SELECT e.*, cc.name AS company_name "
        "FROM employees e "
        "LEFT JOIN client_companies cc ON e.company_id = cc.id "
        "WHERE e.id=?",
        (emp_id,),
    ).fetchone()
    if not employee:
        return RedirectResponse(url="/hr/employees", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="hr/employee_detail.html",
        context={
            "request": request,
            "page_title": f"{employee['name']} - 직원 상세",
            "user_name": user["user_name"],
            "user_role": user["user_role"],
            "employee": employee,
        },
    )


@router.get("/employees/{emp_id}/edit", response_class=HTMLResponse)
async def employee_edit(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    employee = conn.execute(
        "SELECT * FROM employees WHERE id=?", (emp_id,)
    ).fetchone()
    companies = conn.execute(
        "SELECT id, name FROM client_companies WHERE status='active' ORDER BY name"
    ).fetchall()
    if not employee:
        return RedirectResponse(url="/hr/employees", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="hr/employee_form.html",
        context={
            "request": request,
            "page_title": f"{employee['name']} - 정보 수정",
            "user_name": user["user_name"],
            "user_role": user["user_role"],
            "employee": employee,
            "companies": companies,
            "error": "",
        },
    )


@router.post("/employees/{emp_id}/edit", response_class=HTMLResponse)
async def employee_update(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
    name: str = Form(...),
    employee_no: str = Form(""),
    dept: str = Form("경영지원팀"),
    position: str = Form("사원"),
    hire_date: str = Form(""),
    status: str = Form("active"),
    disability_type: str = Form(""),
    disability_grade: str = Form(""),
    emergency_contact: str = Form(""),
    emergency_phone: str = Form(""),
    notes: str = Form(""),
    company_id: str = Form(""),
):
    try:
        conn.execute(
            """UPDATE employees SET
               name=?, employee_no=?, dept=?, position=?, hire_date=?, status=?,
               disability_type=?, disability_grade=?,
               emergency_contact=?, emergency_phone=?, notes=?, company_id=?,
               updated_at=datetime('now','localtime')
               WHERE id=?""",
            (name, employee_no or None, dept, position, hire_date, status,
             disability_type, disability_grade,
             emergency_contact, emergency_phone, notes,
             int(company_id) if company_id else None,
             emp_id),
        )
        conn.commit()
    except Exception:
        employee = conn.execute(
            "SELECT * FROM employees WHERE id=?", (emp_id,)
        ).fetchone()
        companies = conn.execute(
            "SELECT id, name FROM client_companies WHERE status='active' ORDER BY name"
        ).fetchall()
        return templates.TemplateResponse(
            request=request,
            name="hr/employee_form.html",
            context={
                "request": request,
                "page_title": "직원 정보 수정",
                "user_name": user["user_name"],
                "user_role": user["user_role"],
                "employee": employee,
                "companies": companies,
                "error": "사번이 중복되었거나 필수 항목이 누락되었습니다.",
            },
        )
    return RedirectResponse(url=f"/hr/employees/{emp_id}", status_code=303)


PROFILE_COLS = [
    "hand_left", "hand_right", "arm_left", "arm_right", "neck",
    "foot_left", "foot_right", "posture_maintenance",
    "vision", "hearing", "eye_movement", "eyelid_control",
    "speech", "breath_control",
    "reading_level", "sustained_focus", "memory_aid_needed",
    "continuous_work_minutes", "fatigue_pattern", "posture_change_interval",
    "input_overrides", "notes",
]


@router.get("/employees/{emp_id}/profile", response_class=HTMLResponse)
async def capability_profile_form(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    employee = conn.execute(
        "SELECT * FROM employees WHERE id=?", (emp_id,)
    ).fetchone()
    if not employee:
        return RedirectResponse(url="/hr/employees", status_code=303)
    profile = conn.execute(
        "SELECT * FROM capability_profiles WHERE employee_id=? ORDER BY effective_date DESC LIMIT 1",
        (emp_id,),
    ).fetchone()

    tier2, tier3 = None, None
    if profile:
        p = dict(profile)
        tier2 = derive_tier2(p)
        tier3 = derive_tier3(tier2, p)

    return templates.TemplateResponse(
        request=request,
        name="hr/capability_profile.html",
        context={
            "request": request,
            "page_title": f"{employee['name']} - 능력 프로필",
            "user_name": user["user_name"],
            "user_role": user["user_role"],
            "employee": employee,
            "profile": dict(profile) if profile else None,
            "tier2": tier2,
            "tier3": tier3,
        },
    )


@router.post("/employees/{emp_id}/profile", response_class=HTMLResponse)
async def capability_profile_save(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    form = await request.form()
    employee = conn.execute(
        "SELECT * FROM employees WHERE id=?", (emp_id,)
    ).fetchone()
    if not employee:
        return RedirectResponse(url="/hr/employees", status_code=303)

    effective_date = form.get("effective_date", "")
    values = {}
    for col in PROFILE_COLS:
        val = form.get(col, "")
        if col in ("posture_maintenance", "eye_movement", "eyelid_control",
                    "breath_control", "sustained_focus", "memory_aid_needed"):
            values[col] = int(val) if val not in ("", None) else -1
        elif col in ("continuous_work_minutes", "posture_change_interval"):
            values[col] = int(val) if val not in ("", None) else None
        else:
            values[col] = val

    existing = conn.execute(
        "SELECT id FROM capability_profiles WHERE employee_id=? AND effective_date=?",
        (emp_id, effective_date),
    ).fetchone()

    cols_str = ", ".join(PROFILE_COLS)
    placeholders = ", ".join(["?"] * len(PROFILE_COLS))
    col_vals = [values[c] for c in PROFILE_COLS]

    if existing:
        set_clause = ", ".join(f"{c}=?" for c in PROFILE_COLS)
        conn.execute(
            f"UPDATE capability_profiles SET {set_clause}, updated_at=datetime('now','localtime') WHERE id=?",
            col_vals + [existing["id"]],
        )
    else:
        conn.execute(
            f"INSERT INTO capability_profiles (employee_id, effective_date, {cols_str}) VALUES (?,?,{placeholders})",
            [emp_id, effective_date] + col_vals,
        )
    conn.commit()
    return RedirectResponse(url=f"/hr/employees/{emp_id}/profile", status_code=303)


@router.get("/employees/{emp_id}/profile/result", response_class=HTMLResponse)
async def capability_result(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    employee = conn.execute(
        "SELECT * FROM employees WHERE id=?", (emp_id,)
    ).fetchone()
    if not employee:
        return RedirectResponse(url="/hr/employees", status_code=303)
    profile = conn.execute(
        "SELECT * FROM capability_profiles WHERE employee_id=? ORDER BY effective_date DESC LIMIT 1",
        (emp_id,),
    ).fetchone()

    if not profile:
        return RedirectResponse(url=f"/hr/employees/{emp_id}/profile", status_code=303)

    p = dict(profile)
    tier2 = derive_tier2(p)
    tier3 = derive_tier3(tier2, p)

    return templates.TemplateResponse(
        request=request,
        name="hr/capability_result.html",
        context={
            "request": request,
            "page_title": f"{employee['name']} - 능력 분석 결과",
            "user_name": user["user_name"],
            "user_role": user["user_role"],
            "employee": employee,
            "profile": p,
            "tier2": tier2,
            "tier3": tier3,
        },
    )


@router.get("/attendance", response_class=HTMLResponse)
async def hr_attendance(
    request: Request,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    month = request.query_params.get("month", now_kst().strftime("%Y-%m"))
    status_filter = request.query_params.get("status", "")
    company_filter = request.query_params.get("company", "")

    emp_sql = "SELECT id FROM employees WHERE status = 'active'"
    emp_params = []
    if company_filter:
        emp_sql += " AND company_id = ?"
        emp_params.append(int(company_filter))
    emp_rows = conn.execute(emp_sql, emp_params).fetchall()
    emp_ids = [r["id"] for r in emp_rows]

    records = get_attendance_records(conn, emp_ids, month)
    if status_filter:
        records = [r for r in records if r["status"] == status_filter]
    for r in records:
        r.setdefault("company_name", r.get("company_name") or "-")

    total_workers = len(emp_ids)
    summary = get_attendance_summary(records, total_workers)

    companies = conn.execute(
        "SELECT id, name FROM client_companies WHERE status = 'active' ORDER BY name"
    ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="hr/attendance.html",
        context={
            "request": request,
            "page_title": "근태 관리",
            "user_name": user["user_name"],
            "user_role": user["user_role"],
            "records": records,
            "summary": summary,
            "current_month": month,
            "status_filter": status_filter,
            "company_filter": company_filter,
            "companies": companies,
            "months": available_months(),
        },
    )


@router.get("/attendance/{employee_id}", response_class=HTMLResponse)
async def hr_attendance_detail(
    request: Request,
    employee_id: int,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    month = request.query_params.get("month", now_kst().strftime("%Y-%m"))
    worker = get_worker_detail(conn, employee_id)
    if not worker:
        return RedirectResponse(url="/hr/attendance", status_code=303)
    records = get_worker_month_records(conn, employee_id, month)
    summary = worker_month_summary(records)
    cal = build_calendar_data(records, month)
    prev_m, next_m = prev_next_month(month)

    return templates.TemplateResponse(
        request=request,
        name="hr/attendance_detail.html",
        context={
            "request": request,
            "page_title": f"{worker['name']} 근태 상세",
            "user_name": user["user_name"],
            "user_role": user["user_role"],
            "worker": worker,
            "records": records,
            "summary": summary,
            "cal": cal,
            "current_month": month,
            "prev_month": prev_m,
            "next_month": next_m,
            "back_url": "/hr/attendance",
        },
    )
