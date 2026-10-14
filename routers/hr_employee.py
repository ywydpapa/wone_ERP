import os
import uuid

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from core.deps import get_db, require_login, templates
from core.constants import DISABILITY_TYPES
from routers._helpers import get_page
from core.capability import derive_tier2, derive_tier3
from core.severance import calc_severance
from core import audit

CERT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "var", "uploads", "certs")

router = APIRouter()

PROFILE_COLS = [
    "hand_left", "hand_right", "arm_left", "arm_right", "neck",
    "foot_left", "foot_right", "posture_maintenance",
    "vision", "hearing", "eye_movement", "eyelid_control",
    "speech", "breath_control",
    "reading_level", "sustained_focus", "memory_aid_needed",
    "continuous_work_minutes", "fatigue_pattern", "posture_change_interval",
    "input_overrides", "notes",
]


async def _save_cert_file(upload):
    if not upload or not upload.filename:
        return ""
    os.makedirs(CERT_DIR, exist_ok=True)
    ext = os.path.splitext(upload.filename)[1]
    fname = f"{uuid.uuid4().hex[:12]}{ext}"
    path = os.path.join(CERT_DIR, fname)
    content = await upload.read()
    with open(path, "wb") as f:
        f.write(content)
    return f"uploads/certs/{fname}"


@router.get("/employees", response_class=HTMLResponse)
async def employee_list(
    request: Request,
    q: str = "",
    dept: str = "",
    company: str = "",
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
    if company:
        base_sql += " AND e.company_id = ?"
        params.append(int(company))
    total = conn.execute("SELECT COUNT(*) " + base_sql, params).fetchone()[0]
    sql = "SELECT e.*, cc.name AS company_name " + base_sql + " ORDER BY e.employee_no LIMIT ? OFFSET ?"
    employees = conn.execute(sql, params + [per_page, (page - 1) * per_page]).fetchall()
    depts = conn.execute(
        "SELECT DISTINCT dept FROM employees ORDER BY dept"
    ).fetchall()
    companies = conn.execute(
        "SELECT id, name FROM client_companies ORDER BY name"
    ).fetchall()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request=request,
        name="hr/employee_list.html",
        context={
            "request": request,
            "page_title": "인사관리 - 직원 목록",
            "user_name": user["name"],
            "user_role": user["role"],
            "employees": employees,
            "depts": [r["dept"] for r in depts],
            "companies": [dict(r) for r in companies],
            "q": q,
            "selected_dept": dept,
            "selected_company": company,
            "total_count": total,
            "page": page,
            "total_pages": total_pages,
            "base_url": f"/hr/employees?q={q}&dept={dept}&company={company}&",
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
            "user_name": user["name"],
            "user_role": user["role"],
            "employee": None,
            "companies": companies,
            "disability_types": DISABILITY_TYPES,
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
    gender: str = Form(""),
    birth_date: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    disability_type: str = Form(""),
    disability_grade: str = Form(""),
    emergency_contact: str = Form(""),
    emergency_phone: str = Form(""),
    notes: str = Form(""),
    company_id: str = Form(""),
    resident_no: str = Form(""),
    job_title: str = Form(""),
    disability_cert_file: UploadFile = File(None),
):
    cert_path = await _save_cert_file(disability_cert_file)
    try:
        cur = conn.execute(
            """INSERT INTO employees
               (name, employee_no, dept, position, hire_date, status,
                gender, birth_date, phone, email, address,
                disability_type, disability_grade,
                emergency_contact, emergency_phone,
                notes, company_id,
                resident_no, job_title, disability_cert_file)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, employee_no or None, dept, position, hire_date, status,
             gender, birth_date, phone, email, address,
             disability_type, disability_grade,
             emergency_contact, emergency_phone,
             notes,
             int(company_id) if company_id else None,
             resident_no, job_title, cert_path),
        )
        new_id = cur.lastrowid
        audit.log(conn, user["id"], "employee_create", "employee", new_id, name,
                  company_id=int(company_id) if company_id else None)
        conn.commit()
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
                "user_name": user["name"],
                "user_role": user["role"],
                "employee": None,
                "companies": companies,
                "disability_types": DISABILITY_TYPES,
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
            "user_name": user["name"],
            "user_role": user["role"],
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
            "user_name": user["name"],
            "user_role": user["role"],
            "employee": employee,
            "companies": companies,
            "disability_types": DISABILITY_TYPES,
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
    gender: str = Form(""),
    birth_date: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    disability_type: str = Form(""),
    disability_grade: str = Form(""),
    emergency_contact: str = Form(""),
    emergency_phone: str = Form(""),
    notes: str = Form(""),
    company_id: str = Form(""),
    resident_no: str = Form(""),
    job_title: str = Form(""),
    disability_cert_file: UploadFile = File(None),
):
    cert_path = await _save_cert_file(disability_cert_file)
    old_row = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    try:
        sql = """UPDATE employees SET
               name=?, employee_no=?, dept=?, position=?, hire_date=?, status=?,
               gender=?, birth_date=?, phone=?, email=?, address=?,
               disability_type=?, disability_grade=?,
               emergency_contact=?, emergency_phone=?,
               notes=?, company_id=?,
               resident_no=?, job_title=?,
               updated_at=datetime('now','localtime')"""
        company_id_val = int(company_id) if company_id else None
        params = [
            name, employee_no or None, dept, position, hire_date, status,
            gender, birth_date, phone, email, address,
            disability_type, disability_grade,
            emergency_contact, emergency_phone,
            notes,
            company_id_val,
            resident_no, job_title,
        ]
        new_vals = {"name": name, "employee_no": employee_no or None, "dept": dept, "position": position,
                    "hire_date": hire_date, "status": status, "gender": gender, "birth_date": birth_date,
                    "phone": phone, "email": email, "address": address, "disability_type": disability_type,
                    "disability_grade": disability_grade, "emergency_contact": emergency_contact,
                    "emergency_phone": emergency_phone, "notes": notes, "company_id": company_id_val,
                    "job_title": job_title}
        if cert_path:
            sql += ", disability_cert_file=?"
            params.append(cert_path)
            new_vals["disability_cert_file"] = cert_path
        sql += " WHERE id=?"
        params.append(emp_id)
        conn.execute(sql, params)
        changed = audit.diff(dict(old_row), new_vals)
        audit.log(conn, user["id"], "employee_update", "employee", emp_id, name,
                  detail=changed, company_id=company_id_val)
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
                "user_name": user["name"],
                "user_role": user["role"],
                "employee": employee,
                "companies": companies,
                "disability_types": DISABILITY_TYPES,
                "error": "사번이 중복되었거나 필수 항목이 누락되었습니다.",
            },
        )
    return RedirectResponse(url=f"/hr/employees/{emp_id}", status_code=303)


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
    bw_class, bw_label = "bg-secondary", "저속"
    if profile:
        p = dict(profile)
        tier2 = derive_tier2(p)
        tier3 = derive_tier3(tier2, p)
        bw_map = {"high": ("bg-success", "고속"), "medium": ("bg-warning text-dark", "중속")}
        bw_class, bw_label = bw_map.get(tier2.bandwidth, ("bg-secondary", "저속"))

    return templates.TemplateResponse(
        request=request,
        name="hr/capability_profile.html",
        context={
            "request": request,
            "page_title": f"{employee['name']} - 능력 프로필",
            "user_name": user["name"],
            "user_role": user["role"],
            "employee": employee,
            "profile": dict(profile) if profile else None,
            "tier2": tier2,
            "tier3": tier3,
            "bw_class": bw_class,
            "bw_label": bw_label,
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


@router.get("/employees/{emp_id}/resign", response_class=HTMLResponse)
async def resign_form(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    emp = conn.execute(
        "SELECT e.*, cc.name AS company_name "
        "FROM employees e LEFT JOIN client_companies cc ON e.company_id=cc.id "
        "WHERE e.id=?",
        (emp_id,),
    ).fetchone()
    if not emp:
        return RedirectResponse(url="/hr/employees", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="hr/resign_form.html",
        context={
            "request": request,
            "page_title": f"{emp['name']} - 퇴사 처리",
            "user_name": user["name"],
            "user_role": user["role"],
            "employee": emp,
        },
    )


@router.post("/employees/{emp_id}/resign", response_class=HTMLResponse)
async def resign_submit(
    request: Request,
    emp_id: int,
    resign_date: str = Form(...),
    resign_reason: str = Form(""),
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        return RedirectResponse(url="/hr/employees", status_code=303)

    conn.execute(
        "UPDATE employees SET resign_date=?, resign_reason=?, status='retired', "
        "updated_at=datetime('now','localtime') WHERE id=?",
        (resign_date, resign_reason, emp_id),
    )
    audit.log(conn, user["id"], "employee_resign", "employee", emp_id, emp["name"], company_id=emp["company_id"])
    conn.commit()

    sev = calc_severance(conn, emp_id, resign_date=resign_date)
    if sev:
        today = resign_date
        conn.execute(
            """INSERT INTO severance_records
               (employee_id, calc_date, avg_salary, tenure_days, amount, status, created_by)
               VALUES (?,?,?,?,?,'pending',?)""",
            (emp_id, today, sev["avg_salary"], sev["tenure_days"], sev["amount"], user["id"]),
        )
        conn.commit()

    return RedirectResponse(url=f"/severance/{emp_id}", status_code=303)


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
            "user_name": user["name"],
            "user_role": user["role"],
            "employee": employee,
            "profile": p,
            "tier2": tier2,
            "tier3": tier3,
        },
    )
