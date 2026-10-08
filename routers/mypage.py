from core.tz import now_kst
from core.auth import hash_pw, verify_pw
import os
import time
import uuid
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import timedelta
from urllib.parse import quote
from core.db import with_status_meta
from core.deps import get_db, require_login, templates, get_employee_id
from core.attendance import available_months, STATUS_LABELS
from core.payroll import build_payslip_detail
from core.weekly_hours import get_weekly_hours
from core.holiday import is_holiday
from core.work_schedule import get_schedule, calc_work_minutes, is_late
from core.leave import validate_leave_request, LEAVE_TYPES, create_leave, cancel_leave
from core.approval import create_approval
import json
from core.constants import ACCOMMODATION_CATEGORY_LABELS, ACCOMMODATION_STATUS_LABELS, APPEAL_TYPE_LABELS, COMPANY_INFO
from core.export import mask_rno
from core.withholding import get_employee_yearly
from routers._helpers import get_page, save_upload

router = APIRouter(prefix="/mypage")


def _verified(request):
    # 급여명세서/원천징수부 공통 본인 확인. 30분간 유효
    verified_at = request.session.get("payslip_verified_at", 0)
    return (time.time() - verified_at) < 1800


@router.get("/", response_class=HTMLResponse)
async def mypage_index(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    now = now_kst()
    month = now.strftime("%Y-%m")

    profile = {}
    company_name = ""
    att_count = 0
    att_recent = []
    on_time_rate = 100
    annual_total = 15
    annual_used = 0
    leave_recent = []
    has_payslip = False
    payslip_label = ""
    accom_pending = 0

    if emp_id:
        row = conn.execute(
            "SELECT name, employee_no, dept, position, company_id, "
            "annual_leave_total, annual_leave_used "
            "FROM employees WHERE id=?", (emp_id,)
        ).fetchone()
        if row:
            profile = dict(row)
            co = conn.execute(
                "SELECT name FROM client_companies WHERE id=?", (row["company_id"],)
            ).fetchone()
            company_name = co["name"] if co else ""
            annual_total = row["annual_leave_total"] or 15
            annual_used = row["annual_leave_used"] or 0

        # 근태
        att_rows = conn.execute(
            "SELECT work_date, clock_in, clock_out, work_minutes, status "
            "FROM attendance WHERE employee_id=? AND work_date LIKE ? "
            "ORDER BY work_date DESC LIMIT 5",
            (emp_id, f"{month}%")
        ).fetchall()
        att_recent = [dict(r) for r in att_rows]
        att_count = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE employee_id=? AND work_date LIKE ?",
            (emp_id, f"{month}%")
        ).fetchone()[0]
        late = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE employee_id=? AND work_date LIKE ? AND status='late'",
            (emp_id, f"{month}%")
        ).fetchone()[0]
        on_time_rate = round((att_count - late) / att_count * 100) if att_count else 100

        for r in att_recent:
            mins = r.get("work_minutes") or 0
            h, m = mins // 60, mins % 60
            r["work_hours"] = (f"{h}시간 {m}분" if m else f"{h}시간") if mins else "-"

        # 휴가
        leave_rows = conn.execute(
            "SELECT start_date, leave_type, status FROM leave_requests "
            "WHERE employee_id=? ORDER BY created_at DESC LIMIT 3",
            (emp_id,)
        ).fetchall()
        leave_recent = [dict(r) for r in leave_rows]
        for r in leave_recent:
            r["leave_type_label"] = LEAVE_TYPES.get(r.get("leave_type", ""), {}).get("label", r.get("leave_type", ""))

        # 급여
        today = now.strftime("%Y-%m-%d")
        ps = conn.execute(
            "SELECT pay_year, pay_month FROM payslips "
            "WHERE employee_id=? AND status='confirmed' AND pay_date<=? "
            "ORDER BY pay_year DESC, pay_month DESC LIMIT 1",
            (emp_id, today)
        ).fetchone()
        if ps:
            has_payslip = True
            payslip_label = f"{ps['pay_month']}월 급여"

        # 편의지원
        accom_pending = conn.execute(
            "SELECT COUNT(*) FROM accommodation_requests "
            "WHERE employee_id=? AND status IN ('pending','reviewing')",
            (emp_id,)
        ).fetchone()[0]

    return templates.TemplateResponse(request=request, name="mypage/index.html", context={
        "page_title": "마이페이지",
        "user_name": user["name"],
        "profile": profile,
        "company_name": company_name,
        "att_count": att_count,
        "att_recent": att_recent,
        "on_time_rate": on_time_rate,
        "annual_total": annual_total,
        "annual_used": annual_used,
        "annual_remaining": round(annual_total - annual_used, 1),
        "leave_recent": leave_recent,
        "has_payslip": has_payslip,
        "payslip_label": payslip_label,
        "accom_pending": accom_pending,
    })


@router.get("/attendance", response_class=HTMLResponse)
async def mypage_attendance(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    month = request.query_params.get("month", now_kst().strftime("%Y-%m"))
    emp_id = get_employee_id(conn, user["id"])
    records = []
    if emp_id:
        rows = conn.execute(
            "SELECT * FROM attendance WHERE employee_id = ? AND work_date LIKE ? ORDER BY work_date DESC",
            (emp_id, f"{month}%"),
        ).fetchall()
        records = [dict(r) for r in rows]

    for r in records:
        r["status_label"] = STATUS_LABELS.get(r.get("status", ""), r.get("status", ""))
        mins = r.get("work_minutes") or 0
        h, m = mins // 60, mins % 60
        r["work_hours"] = (f"{h}시간 {m}분" if m else f"{h}시간") if mins else "-"

    pending_appeals = 0
    missing_clockout = None
    if emp_id:
        pending_appeals = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE employee_id=? AND appeal='pending'",
            (emp_id,),
        ).fetchone()[0]
        yesterday = (now_kst() - timedelta(days=1)).date().isoformat()
        miss_row = conn.execute(
            "SELECT work_date FROM attendance WHERE employee_id=? AND work_date=? "
            "AND clock_in IS NOT NULL AND clock_out IS NULL", (emp_id, yesterday)
        ).fetchone()
        if miss_row:
            missing_clockout = miss_row["work_date"]

    work_days = len(records)
    late_days = sum(1 for r in records if r.get("status") == "late")
    on_time_rate = round((work_days - late_days) / work_days * 100) if work_days > 0 else 100
    total_minutes = sum(r.get("work_minutes") or 0 for r in records)
    stats = {
        "work_days": work_days,
        "total_hours": int(total_minutes // 60),
    }

    # 이번 주 근무시간
    today_str = now_kst().date().isoformat()
    week_hours = get_weekly_hours(conn, emp_id, today_str) if emp_id else 0.0

    return templates.TemplateResponse(
        request=request, name="mypage/attendance.html", context={
            "request": request,
            "page_title": "근태 현황",
            "user_name": user["name"],
            "pending_appeals": pending_appeals,
            "missing_clockout": missing_clockout,
            "records": records,
            "current_month": month,
            "months": available_months(),
            "on_time_rate": on_time_rate,
            "stats": stats,
            "week_hours": week_hours,
        }
    )


@router.post("/attendance/clock-in")
async def clock_in(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    if not emp_id:
        return RedirectResponse(url="/", status_code=303)
    today = now_kst().date().isoformat()
    existing = conn.execute(
        "SELECT id, clock_in FROM attendance WHERE employee_id=? AND work_date=?",
        (emp_id, today),
    ).fetchone()
    clock_time = now_kst().strftime("%H:%M:%S")
    emp_co = conn.execute("SELECT company_id FROM employees WHERE id=?", (emp_id,)).fetchone()
    sched = get_schedule(conn, emp_co["company_id"] if emp_co else None)
    if is_holiday(conn, today):
        status = "holiday"
    elif is_late(clock_time, sched):
        status = "late"
    else:
        status = "normal"
    if existing:
        if not existing["clock_in"]:
            conn.execute(
                "UPDATE attendance SET clock_in=?, status=? WHERE id=?",
                (clock_time, status, existing["id"]),
            )
            conn.commit()
    else:
        conn.execute(
            "INSERT INTO attendance (employee_id, work_date, clock_in, status) VALUES (?,?,?,?)",
            (emp_id, today, clock_time, status),
        )
        conn.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/attendance/clock-out")
async def clock_out(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    if not emp_id:
        return RedirectResponse(url="/", status_code=303)
    today = now_kst().date().isoformat()
    existing = conn.execute(
        "SELECT id, clock_in FROM attendance WHERE employee_id=? AND work_date=?",
        (emp_id, today),
    ).fetchone()
    if not existing or not existing["clock_in"]:
        return RedirectResponse(url="/", status_code=303)
    clock_time = now_kst().strftime("%H:%M:%S")
    cin = existing["clock_in"]
    emp_co = conn.execute("SELECT company_id FROM employees WHERE id=?", (emp_id,)).fetchone()
    sched = get_schedule(conn, emp_co["company_id"] if emp_co else None)
    work_mins, _ = calc_work_minutes(cin, clock_time, sched)
    end_h, end_m = int(sched["end_time"][:2]), int(sched["end_time"][3:5])
    out_h, out_m = int(clock_time[:2]), int(clock_time[3:5])
    is_early = (out_h * 60 + out_m) < (end_h * 60 + end_m)
    cin_status = conn.execute(
        "SELECT status FROM attendance WHERE id=?", (existing["id"],)
    ).fetchone()
    was_late = cin_status and cin_status["status"] == "late"
    if was_late and is_early:
        status = "late_early"
    elif was_late:
        status = "late"
    elif is_early:
        status = "early_leave"
    else:
        status = "normal"
    conn.execute(
        "UPDATE attendance SET clock_out=?, work_minutes=?, status=? WHERE id=?",
        (clock_time, work_mins, status, existing["id"]),
    )
    conn.commit()
    return RedirectResponse(url="/", status_code=303)


@router.get("/attendance/{att_id}/appeal", response_class=HTMLResponse)
async def appeal_form(
    request: Request,
    att_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    row = conn.execute(
        "SELECT * FROM attendance WHERE id=? AND employee_id=?", (att_id, emp_id)
    ).fetchone()
    if not row or row["status"] not in ("late", "early_leave", "late_early"):
        return RedirectResponse(url="/mypage/attendance", status_code=303)
    if row["appeal"] == "pending" or row["appeal"] == "approved":
        return RedirectResponse(url="/mypage/attendance", status_code=303)
    # rejected면 재소명 허용 (appeal 리셋)
    if row["appeal"] == "rejected":
        conn.execute(
            "UPDATE attendance SET appeal=NULL, appeal_type=NULL, appeal_reason=NULL, "
            "appeal_file=NULL WHERE id=?", (att_id,)
        )
        conn.commit()

    company = conn.execute(
        "SELECT cc.appeal_guide, cc.appeal_types, cc.appeal_require_file "
        "FROM employees e JOIN client_companies cc ON e.company_id=cc.id "
        "WHERE e.id=?", (emp_id,)
    ).fetchone()
    guide = ""
    allowed_types = list(APPEAL_TYPE_LABELS.keys())
    require_file = False
    if company:
        guide = company["appeal_guide"] or ""
        if company["appeal_types"]:
            allowed_types = json.loads(company["appeal_types"])
        require_file = bool(company["appeal_require_file"])
    filtered_types = {k: v for k, v in APPEAL_TYPE_LABELS.items() if k in allowed_types}

    return templates.TemplateResponse(
        request=request, name="mypage/appeal_form.html", context={
            "request": request,
            "page_title": "지각 소명",
            "user_name": user["name"],
            "att": dict(row),
            "appeal_types": filtered_types,
            "appeal_guide": guide,
            "require_file": require_file,
        }
    )


@router.post("/attendance/{att_id}/appeal")
async def appeal_submit(
    request: Request,
    att_id: int,
    appeal_type: str = Form(...),
    appeal_reason: str = Form(""),
    evidence: UploadFile = File(None),
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    row = conn.execute(
        "SELECT * FROM attendance WHERE id=? AND employee_id=?", (att_id, emp_id)
    ).fetchone()
    if not row or row["status"] not in ("late", "early_leave", "late_early"):
        return RedirectResponse(url="/mypage/attendance", status_code=303)

    file_path = ""
    if evidence and evidence.filename:
        file_path = await save_upload(evidence, upload_dir="var/uploads/appeal")

    disability_yn = 1 if appeal_type == "disability" else 0
    conn.execute(
        "UPDATE attendance SET appeal='pending', appeal_type=?, appeal_reason=?, "
        "appeal_file=?, disability_related=? WHERE id=?",
        (appeal_type, appeal_reason, file_path, disability_yn, att_id),
    )
    conn.commit()
    return RedirectResponse(url="/mypage/attendance", status_code=303)


@router.get("/leave", response_class=HTMLResponse)
async def mypage_leave(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    page = get_page(request)
    per_page = 10
    emp_id = get_employee_id(conn, user["id"])
    requests_list = []
    annual_total = 15
    annual_used = 0
    total_pages = 1
    if emp_id:
        total = conn.execute(
            "SELECT COUNT(*) FROM leave_requests WHERE employee_id = ?", (emp_id,)
        ).fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page)
        rows = conn.execute(
            """SELECT lr.*, a.comment as reject_reason
               FROM leave_requests lr
               LEFT JOIN approvals a ON a.doc_type='leave' AND a.doc_id=lr.id AND a.step=1
               WHERE lr.employee_id = ? ORDER BY lr.created_at DESC
               LIMIT ? OFFSET ?""",
            (emp_id, per_page, (page - 1) * per_page),
        ).fetchall()
        requests_list = with_status_meta(rows)
        emp = conn.execute(
            "SELECT annual_leave_total, annual_leave_used FROM employees WHERE id = ?",
            (emp_id,),
        ).fetchone()
        if emp:
            annual_total = emp["annual_leave_total"] or 15
            annual_used = emp["annual_leave_used"] or 0

    for r in requests_list:
        r["leave_type_label"] = LEAVE_TYPES.get(r.get("leave_type", ""), {}).get("label", r.get("leave_type", ""))

    return templates.TemplateResponse(
        request=request, name="mypage/leave.html", context={
            "request": request,
            "page_title": "연차/휴가 신청",
            "user_name": user["name"],
            "requests": requests_list,
            "annual_total": annual_total,
            "annual_used": annual_used,
            "annual_remaining": round(annual_total - annual_used, 1),
            "page": page,
            "total_pages": total_pages,
            "base_url": "/mypage/leave?",
        }
    )


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "var", "uploads", "leave")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/leave")
async def mypage_leave_post(
    request: Request,
    leave_type: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    days: float = Form(...),
    reason: str = Form(None),
    attachment: UploadFile = File(None),
    half_day_period: str = Form(None),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    saved_filename = None
    if attachment and attachment.filename:
        ext = os.path.splitext(attachment.filename)[1].lower()
        if ext in (".pdf", ".jpg", ".jpeg", ".png"):
            saved_filename = f"{uuid.uuid4().hex[:12]}{ext}"
            filepath = os.path.join(UPLOAD_DIR, saved_filename)
            with open(filepath, "wb") as f:
                f.write(await attachment.read())

    emp_id = get_employee_id(conn, user["id"])
    if emp_id:
        errors = validate_leave_request(conn, emp_id, leave_type, start_date, end_date, days)
        if errors:
            return RedirectResponse(url=f"/mypage/leave?error={quote(errors[0])}", status_code=303)
        create_leave(conn, emp_id, leave_type, start_date, end_date, days,
                     reason or None, saved_filename, half_day_period)
    return RedirectResponse(url="/mypage/leave?success=1", status_code=303)


@router.post("/leave/{leave_id}/cancel")
async def mypage_leave_cancel(
    request: Request,
    leave_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    if emp_id:
        cancel_leave(conn, leave_id, emp_id=emp_id)
    return RedirectResponse(url="/mypage/leave", status_code=303)


@router.get("/payslip", response_class=HTMLResponse)
async def mypage_payslip(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    if not _verified(request):
        return templates.TemplateResponse(
            request=request, name="mypage/payslip_verify.html", context={
                "request": request,
                "page_title": "급여 조회",
                "user_name": user["name"],
                "error": request.query_params.get("error", ""),
                "doc_name": "급여명세서",
                "next": "/mypage/payslip",
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

    emp_id = get_employee_id(conn, user["id"])
    payslip = None
    available_months_list = []

    employee_info = {}
    company_name = ""

    work_stats = None
    calc_notes = None
    items = None

    if emp_id:
        emp_row = conn.execute(
            "SELECT name, employee_no, dept, position, company_id, monthly_work_hours FROM employees WHERE id=?",
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
        available_months_list = [{"year": r["pay_year"], "month": r["pay_month"]} for r in rows]

        row = conn.execute(
            "SELECT * FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=? AND status='confirmed' AND pay_date<=?",
            (emp_id, selected_year, selected_month, today),
        ).fetchone()
        if row:
            payslip = dict(row)
            work_stats, calc_notes, items = build_payslip_detail(
                conn, emp_id, employee_info.get("monthly_work_hours"), payslip
            )

    return templates.TemplateResponse(
        request=request, name="mypage/payslip.html", context={
            "request": request,
            "page_title": "급여 조회",
            "user_name": user["name"],
            "payslip": payslip,
            "available_months": available_months_list,
            "selected_year": selected_year,
            "selected_month": selected_month,
            "employee_info": employee_info,
            "company_name": company_name,
            "work_stats": work_stats,
            "calc_notes": calc_notes,
            "items": items,
        }
    )


@router.get("/payslip/print", response_class=HTMLResponse)
async def mypage_payslip_print(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    if not _verified(request):
        return RedirectResponse(url="/mypage/payslip", status_code=303)

    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
        month = int(request.query_params.get("month", now.month))
    except ValueError:
        return RedirectResponse(url="/mypage/payslip", status_code=303)

    emp_id = get_employee_id(conn, user["id"])
    if not emp_id:
        return RedirectResponse(url="/mypage/payslip", status_code=303)

    today = now.strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT * FROM payslips WHERE employee_id=? AND pay_year=? AND pay_month=? AND status='confirmed' AND pay_date<=?",
        (emp_id, year, month, today),
    ).fetchone()
    if not row:
        return RedirectResponse(url="/mypage/payslip", status_code=303)

    emp_row = conn.execute(
        "SELECT name, employee_no, dept, position, company_id, monthly_work_hours FROM employees WHERE id=?",
        (emp_id,),
    ).fetchone()
    company_name = ""
    if emp_row:
        comp = conn.execute(
            "SELECT name FROM client_companies WHERE id=?", (emp_row["company_id"],)
        ).fetchone()
        if comp:
            company_name = comp["name"]

    payslip = dict(row)
    work_stats, calc_notes, items = build_payslip_detail(
        conn, emp_id, emp_row["monthly_work_hours"] if emp_row else 0, payslip
    )

    return templates.TemplateResponse(
        request=request, name="hr/payslip_print.html", context={
            "payslip": payslip,
            "employee": dict(emp_row) if emp_row else {},
            "company_name": company_name,
            "work_stats": work_stats,
            "calc_notes": calc_notes,
            "items": items,
        }
    )


@router.post("/payslip/verify")
async def mypage_payslip_verify(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    form = await request.form()
    birth_date = form.get("birth_date", "")
    next_url = form.get("next", "/mypage/payslip")
    if next_url not in ("/mypage/payslip", "/mypage/withholding"):
        next_url = "/mypage/payslip"

    emp = conn.execute(
        "SELECT birth_date FROM employees WHERE user_id=?", (user["id"],)
    ).fetchone()
    if emp and emp["birth_date"] == birth_date:
        request.session["payslip_verified_at"] = time.time()
        return RedirectResponse(url=next_url, status_code=303)

    return RedirectResponse(url=f"{next_url}?error=1", status_code=303)


@router.get("/withholding", response_class=HTMLResponse)
async def mypage_withholding(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    if not emp_id:
        return RedirectResponse(url="/mypage", status_code=303)

    if not _verified(request):
        return templates.TemplateResponse(
            request=request, name="mypage/payslip_verify.html", context={
                "request": request,
                "page_title": "근로소득 원천징수부",
                "user_name": user["name"],
                "error": request.query_params.get("error", ""),
                "doc_name": "원천징수부",
                "next": "/mypage/withholding",
            }
        )

    now = now_kst()
    try:
        year = int(request.query_params.get("year", now.year))
    except ValueError:
        year = now.year

    emp = conn.execute(
        "SELECT id, name, employee_no, resident_no, hire_date, resign_date, company_id FROM employees WHERE id=?",
        (emp_id,),
    ).fetchone()
    emp = dict(emp)
    emp["resident_no_masked"] = mask_rno(emp.pop("resident_no"))

    if emp["company_id"]:
        co = conn.execute(
            "SELECT name, business_no, representative, address FROM client_companies WHERE id=?",
            (emp["company_id"],),
        ).fetchone()
        company = dict(co) if co else {}
    else:
        company = {
            "name": COMPANY_INFO["name"], "business_no": COMPANY_INFO["biz_no"],
            "representative": COMPANY_INFO["representative"], "address": COMPANY_INFO["address"],
        }

    record = get_employee_yearly(conn, emp_id, year)

    return templates.TemplateResponse(
        request=request, name="hr/withholding_employee.html", context={
            "request": request,
            "page_title": "근로소득 원천징수부",
            "user_name": user["name"],
            "employee": emp,
            "company": company,
            "record": record,
            "year": year,
            "base_url": "/mypage/withholding",
        }
    )


@router.get("/certificates", response_class=HTMLResponse)
async def mypage_certificates(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    page = get_page(request)
    per_page = 10
    emp_id = get_employee_id(conn, user["id"])
    cert_requests = []
    total_pages = 1
    if emp_id:
        total = conn.execute(
            "SELECT COUNT(*) FROM certificate_requests WHERE employee_id=?", (emp_id,)
        ).fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page)
        rows = conn.execute(
            "SELECT * FROM certificate_requests WHERE employee_id=? ORDER BY requested_at DESC LIMIT ? OFFSET ?",
            (emp_id, per_page, (page - 1) * per_page),
        ).fetchall()
        cert_requests = [dict(r) for r in rows]
        for cr in cert_requests:
            cr['requested_date'] = cr['requested_at'][:10] if cr.get('requested_at') else '-'

    return templates.TemplateResponse(
        request=request, name="mypage/certificates.html", context={
            "request": request,
            "page_title": "증명서 발급",
            "user_name": user["name"],
            "cert_requests": cert_requests,
            "page": page,
            "total_pages": total_pages,
            "base_url": "/mypage/certificates?",
        }
    )


@router.post("/certificates")
async def mypage_certificates_post(
    request: Request,
    cert_type: str = Form(...),
    purpose: str = Form(...),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    if emp_id:
        now = now_kst()
        cur = conn.execute(
            """INSERT INTO certificate_requests (employee_id, cert_type, purpose, status, completed_at)
               VALUES (?, ?, ?, 'completed', datetime('now','localtime'))""",
            (emp_id, cert_type, purpose),
        )
        cert_id = cur.lastrowid
        cert_number = f"CERT-{now.strftime('%Y%m%d')}-{cert_id:04d}"
        conn.execute(
            "UPDATE certificate_requests SET cert_number=? WHERE id=?",
            (cert_number, cert_id),
        )
    return RedirectResponse(url="/mypage/certificates", status_code=303)


@router.get("/accommodation", response_class=HTMLResponse)
async def mypage_accommodation(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    page = get_page(request)
    per_page = 10
    emp_id = get_employee_id(conn, user["id"])
    all_requests = []
    total_pages = 1
    if emp_id:
        total = conn.execute(
            "SELECT COUNT(*) FROM accommodation_requests WHERE employee_id = ?", (emp_id,)
        ).fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page)
        rows = conn.execute(
            "SELECT * FROM accommodation_requests WHERE employee_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (emp_id, per_page, (page - 1) * per_page),
        ).fetchall()
        all_requests = [dict(r) for r in rows]

    for r in all_requests:
        r["category_label"] = ACCOMMODATION_CATEGORY_LABELS.get(r.get("category", ""), r.get("category", ""))
        r["status_label"] = ACCOMMODATION_STATUS_LABELS.get(r.get("status", ""), r.get("status", ""))

    return templates.TemplateResponse(
        request=request, name="mypage/accommodation.html", context={
            "request": request,
            "page_title": "편의지원 신청",
            "user_name": user["name"],
            "requests": all_requests,
            "category_labels": ACCOMMODATION_CATEGORY_LABELS,
            "page": page,
            "total_pages": total_pages,
            "base_url": "/mypage/accommodation?",
        }
    )


@router.post("/accommodation")
async def mypage_accommodation_post(
    request: Request,
    category: str = Form(...),
    title: str = Form(...),
    description: str = Form(None),
    urgency: str = Form("normal"),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    if emp_id:
        cur = conn.execute(
            """INSERT INTO accommodation_requests (employee_id, category, title, description, urgency, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (emp_id, category, title, description or None, urgency),
        )
        create_approval(conn, 'accommodation', cur.lastrowid)
    return RedirectResponse(url="/mypage/accommodation?success=1", status_code=303)


@router.get("/profile", response_class=HTMLResponse)
async def mypage_profile(
    request: Request,
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    user_row = conn.execute(
        "SELECT id, username, name, dept, role FROM users WHERE id = ?",
        (user["id"],),
    ).fetchone()
    emp_row = conn.execute(
        "SELECT * FROM employees WHERE user_id = ?",
        (user["id"],),
    ).fetchone()
    user_info = dict(user_row) if user_row else {}
    emp_info = dict(emp_row) if emp_row else {}

    error = request.query_params.get("error")
    edit_mode = request.query_params.get("edit") == "1"
    return templates.TemplateResponse(
        request=request, name="mypage/profile.html", context={
            "request": request,
            "page_title": "내 정보",
            "user_name": user["name"],
            "user": user_info,
            "employee": emp_info,
            "edit_mode": edit_mode,
            "error": error,
        }
    )


@router.post("/profile/verify")
async def mypage_profile_verify(
    request: Request,
    password: str = Form(...),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    row = conn.execute(
        "SELECT password FROM users WHERE id=?", (user["id"],)
    ).fetchone()
    if not row or not verify_pw(password, row["password"]):
        return RedirectResponse(url="/mypage/profile?error=wrong_password", status_code=303)
    return RedirectResponse(url="/mypage/profile?edit=1", status_code=303)


@router.post("/profile/password")
async def mypage_password_change(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    if new_password != confirm_password:
        return RedirectResponse(url="/mypage/profile?error=pw_mismatch", status_code=303)
    if len(new_password) < 4:
        return RedirectResponse(url="/mypage/profile?error=pw_short", status_code=303)
    row = conn.execute(
        "SELECT password FROM users WHERE id=?", (user["id"],)
    ).fetchone()
    if not row or not verify_pw(current_password, row["password"]):
        return RedirectResponse(url="/mypage/profile?error=pw_wrong", status_code=303)
    new_hash = hash_pw(new_password)
    conn.execute("UPDATE users SET password=? WHERE id=?", (new_hash, user["id"]))
    conn.commit()
    return RedirectResponse(url="/mypage/profile?pw_changed=1", status_code=303)


@router.get("/settings")
async def settings_page(request: Request, user=Depends(require_login)):
    return RedirectResponse(url="/mypage", status_code=303)


@router.post("/profile/save")
async def mypage_profile_save(
    request: Request,
    phone: str = Form(""),
    address: str = Form(""),
    emergency_contact: str = Form(""),
    bank_name: str = Form(""),
    bank_account: str = Form(""),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    conn.execute(
        """UPDATE employees SET phone=?, address=?, emergency_contact=?,
           bank_name=?, bank_account=? WHERE user_id=?""",
        (phone.strip(), address.strip(), emergency_contact.strip(),
         bank_name.strip(), bank_account.strip(), user["id"]),
    )
    conn.commit()
    return RedirectResponse(url="/mypage/profile", status_code=303)
