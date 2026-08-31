from core.tz import now_kst
import hashlib
import os
import time
import uuid
from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
from core.db import get_sqlite, with_status_meta
from core.deps import check_login, get_current_user, templates
from core.attendance import available_months, STATUS_LABELS
from core.leave import validate_leave_request

router = APIRouter(prefix="/mypage", tags=["mypage"])


@router.get("/", response_class=HTMLResponse)
async def mypage_index(request: Request):
    user_id = request.session.get("user_id")
    user_name = request.session.get("user_name", "")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_sqlite()
    try:
        emp = conn.execute(
            "SELECT id, annual_leave_total, annual_leave_used FROM employees WHERE user_id=?",
            (user_id,)
        ).fetchone()
        emp_id = emp["id"] if emp else None

        now = now_kst()
        month_prefix = now.strftime("%Y-%m")

        attendance_days = 0
        leave_remaining = 0
        accommodation_pending = 0

        if emp_id:
            attendance_days = conn.execute(
                "SELECT COUNT(*) FROM attendance WHERE employee_id=? AND work_date LIKE ?",
                (emp_id, f"{month_prefix}%")
            ).fetchone()[0]

            leave_remaining = (emp["annual_leave_total"] or 15) - (emp["annual_leave_used"] or 0)

            accommodation_pending = conn.execute(
                "SELECT COUNT(*) FROM accommodation_requests WHERE employee_id=? AND status IN ('pending','reviewing')",
                (emp_id,)
            ).fetchone()[0]
    finally:
        conn.close()

    return templates.TemplateResponse(request=request, name="mypage/index.html", context={
        "page_title": "마이페이지",
        "user_name": user_name,
        "attendance_days": attendance_days,
        "leave_remaining": leave_remaining,
        "accommodation_pending": accommodation_pending,
    })


def _get_employee_id(conn, user_id: int):
    row = conn.execute(
        "SELECT id FROM employees WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row["id"] if row else None


@router.get("/attendance", response_class=HTMLResponse)
async def mypage_attendance(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    month = request.query_params.get("month", now_kst().strftime("%Y-%m"))
    conn = get_sqlite()
    try:
        emp_id = _get_employee_id(conn, u["user_id"])
        records = []
        if emp_id:
            rows = conn.execute(
                "SELECT * FROM attendance WHERE employee_id = ? AND work_date LIKE ? ORDER BY work_date DESC",
                (emp_id, f"{month}%"),
            ).fetchall()
            records = [dict(r) for r in rows]
    finally:
        conn.close()

    for r in records:
        r["status_label"] = STATUS_LABELS.get(r.get("status", ""), r.get("status", ""))
        mins = r.get("work_minutes") or 0
        h, m = mins // 60, mins % 60
        r["work_hours"] = (f"{h}시간 {m}분" if m else f"{h}시간") if mins else "-"

    work_days = len(records)
    late_days = sum(1 for r in records if r.get("status") == "late")
    on_time_rate = round((work_days - late_days) / work_days * 100) if work_days > 0 else 100
    total_minutes = sum(r.get("work_minutes") or 0 for r in records)
    stats = {
        "work_days": work_days,
        "total_hours": int(total_minutes // 60),
    }

    return templates.TemplateResponse(
        request=request, name="mypage/attendance.html", context={
            "request": request,
            "page_title": "근태 현황",
            "user_name": u["user_name"],
            "records": records,
            "current_month": month,
            "months": available_months(),
            "on_time_rate": on_time_rate,
            "stats": stats,
        }
    )


@router.get("/leave", response_class=HTMLResponse)
async def mypage_leave(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    conn = get_sqlite()
    try:
        emp_id = _get_employee_id(conn, u["user_id"])
        requests_list = []
        annual_total = 15
        annual_used = 0
        if emp_id:
            rows = conn.execute(
                "SELECT * FROM leave_requests WHERE employee_id = ? ORDER BY created_at DESC",
                (emp_id,),
            ).fetchall()
            requests_list = with_status_meta(rows)
            emp = conn.execute(
                "SELECT annual_leave_total, annual_leave_used FROM employees WHERE id = ?",
                (emp_id,),
            ).fetchone()
            if emp:
                annual_total = emp["annual_leave_total"] or 15
                annual_used = emp["annual_leave_used"] or 0
    finally:
        conn.close()

    leave_type_labels = {
        "annual": "연차", "sick": "병가", "special": "특별휴가",
        "maternity": "출산휴가", "paternity": "배우자출산휴가",
        "half_day": "반차", "compensation": "보상휴가",
        "family_event": "경조사",
    }
    for r in requests_list:
        r["leave_type_label"] = leave_type_labels.get(r.get("leave_type", ""), r.get("leave_type", ""))

    return templates.TemplateResponse(
        request=request, name="mypage/leave.html", context={
            "request": request,
            "page_title": "연차/휴가 신청",
            "user_name": u["user_name"],
            "requests": requests_list,
            "annual_total": annual_total,
            "annual_used": annual_used,
            "annual_remaining": round(annual_total - annual_used, 1),
        }
    )


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "uploads", "leave")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/leave")
async def mypage_leave_post(
    request: Request,
    leave_type: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    days: float = Form(...),
    reason: Optional[str] = Form(None),
    attachment: Optional[UploadFile] = File(None),
    half_day_period: Optional[str] = Form(None),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)

    saved_filename = None
    if attachment and attachment.filename:
        ext = os.path.splitext(attachment.filename)[1].lower()
        if ext in (".pdf", ".jpg", ".jpeg", ".png"):
            saved_filename = f"{uuid.uuid4().hex[:12]}{ext}"
            filepath = os.path.join(UPLOAD_DIR, saved_filename)
            with open(filepath, "wb") as f:
                f.write(await attachment.read())

    conn = get_sqlite()
    try:
        emp_id = _get_employee_id(conn, u["user_id"])
        if emp_id:
            errors = validate_leave_request(conn, emp_id, leave_type, start_date, end_date, days)
            if errors:
                from urllib.parse import quote
                return RedirectResponse(url=f"/mypage/leave?error={quote(errors[0])}", status_code=303)
            conn.execute(
                """INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, reason, attachment, half_day_period, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (emp_id, leave_type, start_date, end_date, days, reason or None, saved_filename, half_day_period),
            )
            conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/mypage/leave?success=1", status_code=303)


@router.get("/payslip", response_class=HTMLResponse)
async def mypage_payslip(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)

    verified_at = request.session.get("payslip_verified_at", 0)
    verified = (time.time() - verified_at) < 1800
    if not verified:
        return templates.TemplateResponse(
            request=request, name="mypage/payslip_verify.html", context={
                "request": request,
                "page_title": "급여 조회",
                "user_name": u["user_name"],
                "error": request.query_params.get("error", ""),
            }
        )

    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    try:
        selected_year = int(request.query_params.get("year", now.year))
        selected_month = int(request.query_params.get("month", now.month))
    except ValueError:
        selected_year = now.year
        selected_month = now.month

    conn = get_sqlite()
    try:
        emp_id = _get_employee_id(conn, u["user_id"])
        payslip = None
        available_months = []

        employee_info = {}
        company_name = ""

        if emp_id:
            emp_row = conn.execute(
                "SELECT name, employee_no, dept, position, company_id FROM employees WHERE id=?",
                (emp_id,),
            ).fetchone()
            if emp_row:
                employee_info = dict(emp_row)
                comp = conn.execute(
                    "SELECT name FROM client_companies WHERE id=?",
                    (emp_row["company_id"],),
                ).fetchone()
                if comp:
                    company_name = comp["name"]

            rows = conn.execute(
                "SELECT pay_year, pay_month FROM payslips WHERE employee_id=? AND status='confirmed' AND pay_date<=? ORDER BY pay_year DESC, pay_month DESC",
                (emp_id, today),
            ).fetchall()
            available_months = [{"year": r["pay_year"], "month": r["pay_month"]} for r in rows]

            row = conn.execute(
                "SELECT * FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=? AND status='confirmed' AND pay_date<=?",
                (emp_id, selected_year, selected_month, today),
            ).fetchone()
            if row:
                payslip = dict(row)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request, name="mypage/payslip.html", context={
            "request": request,
            "page_title": "급여 조회",
            "user_name": u["user_name"],
            "payslip": payslip,
            "available_months": available_months,
            "selected_year": selected_year,
            "selected_month": selected_month,
            "employee_info": employee_info,
            "company_name": company_name,
        }
    )


@router.post("/payslip/verify")
async def mypage_payslip_verify(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)

    form = await request.form()
    birth_date = form.get("birth_date", "")

    conn = get_sqlite()
    try:
        emp = conn.execute(
            "SELECT birth_date FROM employees WHERE user_id=?", (u["user_id"],)
        ).fetchone()
        if emp and emp["birth_date"] == birth_date:
            request.session["payslip_verified_at"] = time.time()
            return RedirectResponse(url="/mypage/payslip", status_code=303)
    finally:
        conn.close()

    return RedirectResponse(url="/mypage/payslip?error=1", status_code=303)


@router.get("/certificates", response_class=HTMLResponse)
async def mypage_certificates(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    conn = get_sqlite()
    try:
        emp_id = _get_employee_id(conn, u["user_id"])
        cert_requests = []
        if emp_id:
            rows = conn.execute(
                "SELECT * FROM certificate_requests WHERE employee_id=? ORDER BY requested_at DESC",
                (emp_id,),
            ).fetchall()
            cert_requests = [dict(r) for r in rows]
    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request, name="mypage/certificates.html", context={
            "request": request,
            "page_title": "증명서 발급",
            "user_name": u["user_name"],
            "cert_requests": cert_requests,
        }
    )


@router.post("/certificates")
async def mypage_certificates_post(
    request: Request,
    cert_type: str = Form(...),
    purpose: str = Form(...),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    conn = get_sqlite()
    try:
        emp_id = _get_employee_id(conn, u["user_id"])
        if emp_id:
            conn.execute(
                """INSERT INTO certificate_requests (employee_id, cert_type, purpose, status)
                   VALUES (?, ?, ?, 'pending')""",
                (emp_id, cert_type, purpose),
            )
            conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/mypage/certificates", status_code=303)


@router.get("/accommodation", response_class=HTMLResponse)
async def mypage_accommodation(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    conn = get_sqlite()
    try:
        emp_id = _get_employee_id(conn, u["user_id"])
        all_requests = []
        if emp_id:
            rows = conn.execute(
                "SELECT * FROM accommodation_requests WHERE employee_id = ? ORDER BY created_at DESC",
                (emp_id,),
            ).fetchall()
            all_requests = [dict(r) for r in rows]
    finally:
        conn.close()

    category_labels = {
        "assistive_tech": "보조기기 지원",
        "work_assistant": "근로지원인",
        "workspace_adjust": "작업환경 개선",
    }
    status_labels = {
        "pending": "접수", "reviewing": "검토중", "approved": "승인",
        "rejected": "반려", "completed": "완료",
    }
    for r in all_requests:
        r["category_label"] = category_labels.get(r.get("category", ""), r.get("category", ""))
        r["status_label"] = status_labels.get(r.get("status", ""), r.get("status", ""))

    return templates.TemplateResponse(
        request=request, name="mypage/accommodation.html", context={
            "request": request,
            "page_title": "편의지원 신청",
            "user_name": u["user_name"],
            "requests": all_requests,
            "category_labels": category_labels,
        }
    )


@router.post("/accommodation")
async def mypage_accommodation_post(
    request: Request,
    category: str = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    urgency: str = Form("normal"),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    conn = get_sqlite()
    try:
        emp_id = _get_employee_id(conn, u["user_id"])
        if emp_id:
            conn.execute(
                """INSERT INTO accommodation_requests (employee_id, category, title, description, urgency, status)
                   VALUES (?, ?, ?, ?, ?, 'pending')""",
                (emp_id, category, title, description or None, urgency),
            )
            conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/mypage/accommodation?success=1", status_code=303)


@router.get("/profile", response_class=HTMLResponse)
async def mypage_profile(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    conn = get_sqlite()
    try:
        user_row = conn.execute(
            "SELECT id, username, name, dept, role FROM users WHERE id = ?",
            (u["user_id"],),
        ).fetchone()
        emp_row = conn.execute(
            "SELECT * FROM employees WHERE user_id = ?",
            (u["user_id"],),
        ).fetchone()
        user_info = dict(user_row) if user_row else {}
        emp_info = dict(emp_row) if emp_row else {}
    finally:
        conn.close()

    error = request.query_params.get("error")
    edit_mode = request.query_params.get("edit") == "1"
    return templates.TemplateResponse(
        request=request, name="mypage/profile.html", context={
            "request": request,
            "page_title": "내 정보",
            "user_name": u["user_name"],
            "user": user_info,
            "employee": emp_info,
            "edit_mode": edit_mode,
            "error": error,
        }
    )


@router.post("/profile/verify")
async def mypage_profile_verify(request: Request, password: str = Form(...)):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    hashed = hashlib.sha256(password.encode()).hexdigest()
    conn = get_sqlite()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE id=? AND password=?", (u["user_id"], hashed)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return RedirectResponse(url="/mypage/profile?error=wrong_password", status_code=303)
    return RedirectResponse(url="/mypage/profile?edit=1", status_code=303)


@router.post("/profile/save")
async def mypage_profile_save(
    request: Request,
    phone: str = Form(""),
    address: str = Form(""),
    emergency_contact: str = Form(""),
    bank_name: str = Form(""),
    bank_account: str = Form(""),
):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    u = get_current_user(request)
    conn = get_sqlite()
    try:
        conn.execute(
            """UPDATE employees SET phone=?, address=?, emergency_contact=?,
               bank_name=?, bank_account=? WHERE user_id=?""",
            (phone.strip(), address.strip(), emergency_contact.strip(),
             bank_name.strip(), bank_account.strip(), u["user_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/mypage/profile", status_code=303)
