import os
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.deps import get_db, require_login, require_staff, templates
from core.constants import DISABILITY_TYPES, JOB_CODES
from routers._helpers import MAX_UPLOAD_SIZE, get_page
from core.capability import derive_tier2, derive_tier3
from core.severance import calc_severance, calc_sev_tax, calc_ordinary_daily
from core.leave import get_leave_balance
from core.appointments import log_changes
from core import audit, employee_files
from core.export import csv_response, mask_rno
from core.crypto import enc_rno, dec_rno, valid_rno

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
    ext = os.path.splitext(upload.filename)[1].lower()
    content = await upload.read()
    if len(content) > MAX_UPLOAD_SIZE or not content.startswith(employee_files.SIGS.get(ext, (b"\0",))):
        return ""
    os.makedirs(CERT_DIR, exist_ok=True)
    fname = f"{uuid.uuid4().hex[:12]}{ext}"
    path = os.path.join(CERT_DIR, fname)
    with open(path, "wb") as f:
        f.write(content)
    return f"uploads/certs/{fname}"


# 스태프 범위는 wone 소속 + 급여 위탁 고객사. 그 외 고객사 근로자는 고객사 담당자 관할
SCOPE_SQL = ("(e.company_id IS NULL OR e.company_id IN "
             "(SELECT id FROM client_companies WHERE payroll_delegated=1 AND status='active'))")
COMPANY_SQL = "SELECT id, name FROM client_companies WHERE payroll_delegated=1 AND status='active' ORDER BY name"


def _in_scope(conn, emp_id):
    return conn.execute(f"SELECT 1 FROM employees e WHERE e.id=? AND {SCOPE_SQL}", (emp_id,)).fetchone()


def _company_ok(conn, company_id):
    return not company_id or conn.execute(
        "SELECT 1 FROM client_companies WHERE id=? AND payroll_delegated=1 AND status='active'", (int(company_id),)
    ).fetchone()


EMP_SORTS = {"no": "e.employee_no", "name": "e.name", "company": "cc.name",
             "dept": "e.dept", "status": "e.status", "hire": "e.hire_date"}
EMP_STATUS_LABEL = {"active": "재직", "on_leave": "휴직", "retired": "퇴직"}


def _employee_filter(q, dept, company):
    base_sql = (
        "FROM employees e "
        "LEFT JOIN client_companies cc ON e.company_id = cc.id "
        f"WHERE {SCOPE_SQL}"
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
    return base_sql, params


@router.get("/employees", response_class=HTMLResponse)
async def employee_list(
    request: Request,
    q: str = "",
    dept: str = "",
    company: str = "",
    sort: str = "",
    dir: str = "",
    export: str = "",
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    base_sql, params = _employee_filter(q, dept, company)
    order = EMP_SORTS.get(sort)
    order_sql = f" ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}" if order else " ORDER BY e.employee_no"

    if export == "csv":
        sql = "SELECT e.*, cc.name AS company_name " + base_sql + order_sql
        rows = conn.execute(sql, params).fetchall()
        data = [[r["employee_no"] or "", r["name"], r["company_name"] or "미배정", r["dept"], r["position"],
                 EMP_STATUS_LABEL.get(r["status"], r["status"]), r["hire_date"] or ""] for r in rows]
        return csv_response(["사번", "이름", "소속회사", "부서", "직급", "상태", "입사일"], data, "employees.csv")

    page = get_page(request)
    per_page = 10
    total = conn.execute("SELECT COUNT(*) " + base_sql, params).fetchone()[0]
    sql = "SELECT e.*, cc.name AS company_name " + base_sql + order_sql + " LIMIT ? OFFSET ?"
    employees = conn.execute(sql, params + [per_page, (page - 1) * per_page]).fetchall()
    depts = conn.execute(
        f"SELECT DISTINCT e.dept FROM employees e WHERE {SCOPE_SQL} ORDER BY e.dept"
    ).fetchall()
    companies = conn.execute(COMPANY_SQL).fetchall()

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
            "base_url": f"/hr/employees?q={q}&dept={dept}&company={company}&sort={sort}&dir={dir}&",
            "sort": sort,
            "dir": dir,
        },
    )


@router.get("/employees/new", response_class=HTMLResponse)
async def employee_new(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    companies = conn.execute(COMPANY_SQL).fetchall()
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
            "job_codes": JOB_CODES,
            "error": "",
            "client_mode": False,
            "form_action": "/hr/employees",
            "cancel_url": "/hr/employees",
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
    job_code: str = Form(""),
    disability_cert_file: UploadFile = File(None),
    renew_date: str = Form(""),
    contract_end: str = Form(""),
    career: str = Form(""),
    education: str = Form(""),
    military: str = Form(""),
    license: str = Form(""),
    training: str = Form(""),
    disability_class: str = Form(""),
    veteran_grade: str = Form(""),
    disability_date: str = Form(""),
):
    if resident_no.strip() and not valid_rno(resident_no):
        return JSONResponse({"error": "주민등록번호 형식이 올바르지 않습니다."}, status_code=400)
    if not _company_ok(conn, company_id):
        return JSONResponse({"error": "급여 위탁 고객사만 지정할 수 있습니다."}, status_code=400)
    cert_path = await _save_cert_file(disability_cert_file)
    try:
        cur = conn.execute(
            """INSERT INTO employees
               (name, employee_no, dept, position, hire_date, status,
                gender, birth_date, phone, email, address,
                disability_type, disability_grade,
                emergency_contact, emergency_phone,
                notes, company_id,
                resident_no, job_title, job_code, disability_cert_file,
                renew_date, contract_end, career, education, military, license, training,
                disability_class, veteran_grade, disability_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, employee_no or None, dept, position, hire_date, status,
             gender, birth_date, phone, email, address,
             disability_type, disability_grade,
             emergency_contact, emergency_phone,
             notes,
             int(company_id) if company_id else None,
             enc_rno(resident_no), job_title, job_code or None, cert_path,
             renew_date, contract_end, career, education, military, license, training,
             disability_class, veteran_grade, disability_date),
        )
        new_id = cur.lastrowid
        audit.log(conn, user["id"], "employee_create", "employee", new_id, name,
                  company_id=int(company_id) if company_id else None)
        conn.commit()
    except Exception:
        return JSONResponse({"error": "사번이 중복되었거나 필수 항목이 누락되었습니다."}, status_code=400)
    return RedirectResponse(url=f"/hr/employees/{new_id}", status_code=303)


@router.get("/employees/{emp_id}", response_class=HTMLResponse)
async def employee_detail(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    if not _in_scope(conn, emp_id):
        raise HTTPException(status_code=404)
    employee = conn.execute(
        "SELECT e.*, cc.name AS company_name "
        "FROM employees e "
        "LEFT JOIN client_companies cc ON e.company_id = cc.id "
        "WHERE e.id=?",
        (emp_id,),
    ).fetchone()
    if not employee:
        return RedirectResponse(url="/hr/employees", status_code=303)
    appointments = conn.execute(
        """SELECT a.*, u.name AS created_by_name FROM hr_appointments a
           LEFT JOIN users u ON u.id = a.created_by
           WHERE a.employee_id=? ORDER BY a.id DESC""",
        (emp_id,),
    ).fetchall()
    return templates.TemplateResponse(
        request=request,
        name="hr/employee_detail.html",
        context={
            "request": request,
            "page_title": f"{employee['name']} - 직원 상세",
            "user_name": user["name"],
            "user_role": user["role"],
            "employee": employee,
            "files": employee_files.list_files(conn, emp_id),
            "file_kinds": employee_files.KINDS,
            "appointments": appointments,
        },
    )


@router.get("/employees/{emp_id}/edit", response_class=HTMLResponse)
async def employee_edit(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    if not _in_scope(conn, emp_id):
        raise HTTPException(status_code=404)
    employee = conn.execute(
        "SELECT * FROM employees WHERE id=?", (emp_id,)
    ).fetchone()
    companies = conn.execute(COMPANY_SQL).fetchall()
    if not employee:
        return RedirectResponse(url="/hr/employees", status_code=303)
    if employee["resident_no"]:
        audit.log(conn, user["id"], "resident_no_view", "employee", emp_id, employee["name"],
                  company_id=employee["company_id"])
        conn.commit()
    employee = dict(employee)
    employee["resident_no_masked"] = mask_rno(dec_rno(employee["resident_no"]))
    employee["resident_no"] = ""
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
            "job_codes": JOB_CODES,
            "error": "",
            "client_mode": False,
            "form_action": f"/hr/employees/{emp_id}/edit",
            "cancel_url": f"/hr/employees/{emp_id}",
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
    job_code: str = Form(""),
    disability_cert_file: UploadFile = File(None),
    renew_date: str = Form(""),
    contract_end: str = Form(""),
    career: str = Form(""),
    education: str = Form(""),
    military: str = Form(""),
    license: str = Form(""),
    training: str = Form(""),
    disability_class: str = Form(""),
    veteran_grade: str = Form(""),
    disability_date: str = Form(""),
):
    if not _in_scope(conn, emp_id):
        raise HTTPException(status_code=404)
    if resident_no.strip() and not valid_rno(resident_no):
        return JSONResponse({"error": "주민등록번호 형식이 올바르지 않습니다."}, status_code=400)
    if not _company_ok(conn, company_id):
        return JSONResponse({"error": "급여 위탁 고객사만 지정할 수 있습니다."}, status_code=400)
    cert_path = await _save_cert_file(disability_cert_file)
    old_row = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    rno_val = enc_rno(resident_no) if resident_no.strip() else old_row["resident_no"]
    try:
        sql = """UPDATE employees SET
               name=?, employee_no=?, dept=?, position=?, hire_date=?, status=?,
               gender=?, birth_date=?, phone=?, email=?, address=?,
               disability_type=?, disability_grade=?,
               emergency_contact=?, emergency_phone=?,
               notes=?, company_id=?,
               resident_no=?, job_title=?, job_code=?,
               renew_date=?, contract_end=?, career=?, education=?, military=?, license=?, training=?,
               disability_class=?, veteran_grade=?, disability_date=?,
               updated_at=datetime('now','localtime')"""
        company_id_val = int(company_id) if company_id else None
        params = [
            name, employee_no or None, dept, position, hire_date, status,
            gender, birth_date, phone, email, address,
            disability_type, disability_grade,
            emergency_contact, emergency_phone,
            notes,
            company_id_val,
            rno_val, job_title, job_code or None,
            renew_date, contract_end, career, education, military, license, training,
            disability_class, veteran_grade, disability_date,
        ]
        new_vals = {"name": name, "employee_no": employee_no or None, "dept": dept, "position": position,
                    "hire_date": hire_date, "status": status, "gender": gender, "birth_date": birth_date,
                    "phone": phone, "email": email, "address": address, "disability_type": disability_type,
                    "disability_grade": disability_grade, "emergency_contact": emergency_contact,
                    "emergency_phone": emergency_phone, "notes": notes, "company_id": company_id_val,
                    "job_title": job_title, "job_code": job_code or None,
                    "renew_date": renew_date, "contract_end": contract_end,
                    "career": career, "education": education, "military": military, "license": license,
                    "training": training, "disability_class": disability_class,
                    "veteran_grade": veteran_grade, "disability_date": disability_date}
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
        log_changes(conn, company_id_val, emp_id, changed, user["id"])
        conn.commit()
    except Exception:
        return JSONResponse({"error": "사번이 중복되었거나 필수 항목이 누락되었습니다."}, status_code=400)
    return RedirectResponse(url=f"/hr/employees/{emp_id}", status_code=303)


@router.get("/employees/{emp_id}/profile", response_class=HTMLResponse)
async def capability_profile_form(
    request: Request,
    emp_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    if not _in_scope(conn, emp_id):
        raise HTTPException(status_code=404)
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
    if not _in_scope(conn, emp_id):
        raise HTTPException(status_code=404)
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
    if not _in_scope(conn, emp_id):
        raise HTTPException(status_code=404)
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
            "form_action": f"/hr/employees/{emp_id}/resign",
            "cancel_url": f"/hr/employees/{emp_id}",
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
    if not _in_scope(conn, emp_id):
        raise HTTPException(status_code=404)
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
        tax = calc_sev_tax(sev["amount"], emp["hire_date"], resign_date)

        bal = get_leave_balance(conn, emp_id, date.fromisoformat(resign_date).year)
        leave_days = max(0, bal["remaining"])
        leave_pay = round(leave_days * calc_ordinary_daily(conn, emp_id, resign_date))

        conn.execute(
            """INSERT INTO severance_records
               (employee_id, calc_date, avg_salary, tenure_days, amount,
                income_tax, local_tax, net_amount, leave_days, leave_pay, status, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?)""",
            (emp_id, today, sev["avg_salary"], sev["tenure_days"], sev["amount"],
             tax["income_tax"], tax["local_tax"], tax["net"], leave_days, leave_pay, user["id"]),
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
    if not _in_scope(conn, emp_id):
        raise HTTPException(status_code=404)
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


@router.post("/employees/{emp_id}/files", response_class=HTMLResponse)
async def employee_file_upload(
    request: Request,
    emp_id: int,
    kind: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    if not _in_scope(conn, emp_id):
        raise HTTPException(status_code=404)
    employee = conn.execute("SELECT id, company_id FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not employee:
        raise HTTPException(status_code=404)
    saved = await employee_files.save_file(conn, emp_id, employee["company_id"], kind, file, user["id"])
    if isinstance(saved, str):
        audit.log(conn, user["id"], "employee_file_upload", "employee", emp_id, kind,
                  company_id=employee["company_id"])
        conn.commit()
        return RedirectResponse(url=f"/hr/employees/{emp_id}", status_code=303)
    return RedirectResponse(url=f"/hr/employees/{emp_id}?file_err=1", status_code=303)


@router.post("/employees/{emp_id}/files/{file_id}/delete", response_class=HTMLResponse)
async def employee_file_delete(
    emp_id: int,
    file_id: int,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    if not _in_scope(conn, emp_id):
        raise HTTPException(status_code=404)
    employee = conn.execute("SELECT id FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not employee:
        raise HTTPException(status_code=404)
    if employee_files.delete_file(conn, emp_id, file_id):
        audit.log(conn, user["id"], "employee_file_delete", "employee", emp_id, str(file_id))
        conn.commit()
    return RedirectResponse(url=f"/hr/employees/{emp_id}", status_code=303)
