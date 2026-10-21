from core.tz import now_kst
from core.auth import hash_pw, verify_pw
import os
import time
import uuid
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
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
from core.leave import validate_leave_request, LEAVE_TYPES, create_leave, get_leave_balance, cancel_block
from core.approval import OPEN, hr_approvers, open_doc, pick_lines, preset_lines, withdraw_doc
from core.books import book_of
import json
from core.constants import ACCOMMODATION_CATEGORY_LABELS, ACCOMMODATION_STATUS_LABELS, APPEAL_TYPE_LABELS, COMPANY_INFO
from core.export import mask_rno, mask_acct
from core.crypto import dec_rno
from core.withholding import get_employee_yearly
from routers._helpers import get_page, save_upload
from core import audit
from core.notification import create_bulk_notifications
from core.rate_limit import get_client_ip

router = APIRouter(prefix="/mypage")


def _approvers(conn, user, form_key):
    # 기본 결재선 없고 HR 담당자 여럿일 때만 신청 화면에서 선택
    book = book_of(conn, user) or 0
    cands = hr_approvers(conn, book)
    return book, cands, (len(cands) > 1 and not preset_lines(conn, book, form_key))


def _pick(conn, user, form_key, approver_id):
    book, cands, _ = _approvers(conn, user, form_key)
    pick = approver_id or (cands[0]["id"] if len(cands) == 1 else 0)
    lines = pick_lines(conn, book, form_key, user["id"], pick, cands)
    if lines:
        return book, lines, None
    return book, None, "결재자를 선택해 주세요." if cands else "결재 담당자가 지정되지 않았습니다. 회사 담당자에게 문의해 주세요."


def _appeal_eligible(row):
    # 퇴근 기록 누락도 정정 요청 대상
    if row["status"] in ("late", "early_leave", "late_early", "absent"):
        return True
    return bool(row["clock_in"]) and not row["clock_out"]


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
            "SELECT name, employee_no, dept, position, company_id "
            "FROM employees WHERE id=?", (emp_id,)
        ).fetchone()
        if row:
            profile = dict(row)
            co = conn.execute(
                "SELECT name FROM client_companies WHERE id=?", (row["company_id"],)
            ).fetchone()
            company_name = co["name"] if co else ""
            bal = get_leave_balance(conn, emp_id, now.year)
            annual_total = bal["total"]
            annual_used = bal["used"]

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
    if not row or not _appeal_eligible(row):
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
            "page_title": "근태 정정 요청",
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
    desired_clock_in: str = Form(""),
    desired_clock_out: str = Form(""),
    evidence: UploadFile = File(None),
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    row = conn.execute(
        "SELECT * FROM attendance WHERE id=? AND employee_id=?", (att_id, emp_id)
    ).fetchone()
    if not row or not _appeal_eligible(row):
        return RedirectResponse(url="/mypage/attendance", status_code=303)

    file_path = ""
    if evidence and evidence.filename:
        file_path = await save_upload(evidence, upload_dir="var/uploads/appeal")

    disability_yn = 1 if appeal_type == "disability" else 0
    conn.execute(
        "UPDATE attendance SET appeal='pending', appeal_type=?, appeal_reason=?, "
        "appeal_file=?, disability_related=?, appeal_desired_clock_in=?, appeal_desired_clock_out=? WHERE id=?",
        (appeal_type, appeal_reason, file_path, disability_yn,
         desired_clock_in.strip() or None, desired_clock_out.strip() or None, att_id),
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
            """SELECT * FROM leave_requests
               WHERE employee_id = ? ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (emp_id, per_page, (page - 1) * per_page),
        ).fetchall()
        requests_list = with_status_meta(rows)
        bal = get_leave_balance(conn, emp_id, now_kst().year)
        annual_total = bal["total"]
        annual_used = bal["used"]

    today = now_kst().date().isoformat()
    for r in requests_list:
        r["leave_type_label"] = LEAVE_TYPES.get(r.get("leave_type", ""), {}).get("label", r.get("leave_type", ""))
        cdoc = conn.execute("SELECT status FROM erp_docs WHERE id=?", (r["cancel_doc_id"],)).fetchone() if r["cancel_doc_id"] else None
        r["cancel_pending"] = bool(cdoc and cdoc["status"] in OPEN)
        r["cancel_rejected"] = bool(cdoc and cdoc["status"] == "rejected")
        r["cancelable"] = (r["status"] == "approved" and not r["cancel_pending"]
                           and r["start_date"] >= today and not cancel_block(conn, r))
    _, cands, choose = _approvers(conn, user, "leave")

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
            "approvers": cands if choose else [],
            "notice": request.query_params.get("notice", ""),
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
    approver_id: int = Form(0),
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
        book, lines, err = _pick(conn, user, "leave", approver_id)
        if err:
            return RedirectResponse(url=f"/mypage/leave?error={quote(err)}", status_code=303)
        label = LEAVE_TYPES.get(leave_type, {}).get("label", leave_type)
        content = f"휴가 유형 {label}\n기간 {start_date} ~ {end_date} ({days:g}일)\n사유 {reason or '-'}"
        doc_id = open_doc(conn, user, book, "leave", f"휴가신청 {user['name']} {start_date}~{end_date}", content, lines)
        create_leave(conn, emp_id, leave_type, start_date, end_date, days,
                     reason or None, saved_filename, half_day_period, doc_id)
        conn.commit()
    return RedirectResponse(url="/mypage/leave?success=1", status_code=303)


@router.post("/leave/{leave_id}/cancel")
async def mypage_leave_cancel(
    request: Request,
    leave_id: int,
    reason: str = Form(""),
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    lr = conn.execute(
        "SELECT * FROM leave_requests WHERE id=? AND employee_id=?",
        (leave_id, get_employee_id(conn, user["id"])),
    ).fetchone()
    if not lr:
        raise HTTPException(status_code=404)

    if lr["status"] == "pending":
        doc = conn.execute("SELECT * FROM erp_docs WHERE id=?", (lr["doc_id"],)).fetchone()
        # 이관 시 결재자를 못 찾은 신청은 문서 없음
        if doc and not withdraw_doc(conn, doc, user, "withdrawn"):
            return RedirectResponse(url=f"/mypage/leave?error={quote('결재가 진행된 신청은 취소할 수 없습니다.')}", status_code=303)
        conn.execute("UPDATE leave_requests SET status='cancelled' WHERE id=?", (leave_id,))
        conn.commit()
        return RedirectResponse(url="/mypage/leave", status_code=303)

    # 승인 후 취소는 연차 복원과 근태 반영이 수반되므로 원 결재자에게 재결재
    reason = reason.strip()
    if lr["status"] != "approved":
        err = "취소할 수 없는 신청입니다."
    elif not reason:
        err = "취소 사유를 입력하세요."
    elif lr["start_date"] < now_kst().date().isoformat():
        err = "이미 시작된 휴가는 회사 담당자에게 취소를 요청해 주세요."
    elif lr["cancel_doc_id"] and conn.execute(
        "SELECT status FROM erp_docs WHERE id=?", (lr["cancel_doc_id"],)
    ).fetchone()["status"] in OPEN:
        err = "이미 취소 신청이 진행 중입니다."
    else:
        err = cancel_block(conn, lr)
    if err:
        return RedirectResponse(url=f"/mypage/leave?notice={quote(err)}", status_code=303)

    prev = conn.execute(
        "SELECT approver_id FROM approval_lines WHERE doc_id=? AND step > 0 AND role != '참조' ORDER BY step LIMIT 1", (lr["doc_id"],)
    ).fetchone() if lr["doc_id"] else None
    book, lines, err = _pick(conn, user, "leave", prev["approver_id"] if prev else 0)
    if err:
        return RedirectResponse(url=f"/mypage/leave?notice={quote(err)}", status_code=303)
    label = LEAVE_TYPES.get(lr["leave_type"], {}).get("label", lr["leave_type"])
    content = f"취소 대상 {label} {lr['start_date']} ~ {lr['end_date']} ({lr['days']:g}일)\n취소 사유 {reason}"
    doc_id = open_doc(conn, user, book, "leave_cancel",
                      f"휴가취소신청 {user['name']} {lr['start_date']}~{lr['end_date']}", content, lines)
    conn.execute("UPDATE leave_requests SET cancel_doc_id=?, cancel_reason=? WHERE id=?", (doc_id, reason, leave_id))
    conn.commit()
    return RedirectResponse(url=f"/mypage/leave?notice={quote('취소 신청이 접수되었습니다.')}", status_code=303)


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
        # 월 미지정 시 최근 확정 명세서 기준
        if rows and "month" not in request.query_params:
            selected_year, selected_month = rows[0]["pay_year"], rows[0]["pay_month"]

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
            "viewer_name": user["name"],
            "viewed_at": now_kst().strftime("%Y-%m-%d %H:%M"),
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
    emp["resident_no_masked"] = mask_rno(dec_rno(emp.pop("resident_no")))

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


# 담당자 발급, 인쇄 대상. 그 외 종류는 즉시 발급 유지
CERT_PRINTABLE_TYPES = ("재직증명서", "경력증명서")


def _cert_context(conn, cert_id):
    row = conn.execute(
        "SELECT cr.*, e.name AS emp_name, e.employee_no, e.dept, e.position, "
        "e.hire_date, e.resign_date, e.company_id "
        "FROM certificate_requests cr JOIN employees e ON e.id = cr.employee_id "
        "WHERE cr.id=?", (cert_id,),
    ).fetchone()
    if not row or row["cert_type"] not in CERT_PRINTABLE_TYPES:
        return None
    cert = dict(row)
    if cert["company_id"]:
        co = conn.execute(
            "SELECT name, business_no, representative FROM client_companies WHERE id=?",
            (cert["company_id"],),
        ).fetchone()
        company = dict(co) if co else {}
    else:
        company = {
            "name": COMPANY_INFO["name"], "business_no": COMPANY_INFO["biz_no"],
            "representative": COMPANY_INFO["representative"],
        }
    cert["company"] = company
    cert["period"] = f"{cert['hire_date'] or '-'} ~ {cert['resign_date'] or '현재'}"
    return cert


def _issue_cert(conn, cert_id, issued_by):
    now = now_kst()
    cert_number = f"CERT-{now.strftime('%Y%m%d')}-{cert_id:04d}"
    conn.execute(
        "UPDATE certificate_requests SET status='completed', cert_number=?, "
        "completed_at=datetime('now','localtime'), issued_by=? WHERE id=? AND status='pending'",
        (cert_number, issued_by, cert_id),
    )
    conn.commit()


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
        if cert_type in CERT_PRINTABLE_TYPES:
            conn.execute(
                "INSERT INTO certificate_requests (employee_id, cert_type, purpose, status) "
                "VALUES (?, ?, ?, 'pending')",
                (emp_id, cert_type, purpose),
            )
        else:
            now = now_kst()
            cur = conn.execute(
                "INSERT INTO certificate_requests (employee_id, cert_type, purpose, status, completed_at) "
                "VALUES (?, ?, ?, 'completed', datetime('now','localtime'))",
                (emp_id, cert_type, purpose),
            )
            cert_id = cur.lastrowid
            conn.execute(
                "UPDATE certificate_requests SET cert_number=? WHERE id=?",
                (f"CERT-{now.strftime('%Y%m%d')}-{cert_id:04d}", cert_id),
            )
        conn.commit()
    return RedirectResponse(url="/mypage/certificates", status_code=303)


@router.get("/certificates/{cert_id}/print", response_class=HTMLResponse)
async def mypage_certificate_print(
    request: Request,
    cert_id: int,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    cert = _cert_context(conn, cert_id)
    if not cert or cert["employee_id"] != emp_id or cert["status"] != "completed":
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request, name="common/certificate_print.html", context={
            "request": request,
            "cert": cert,
            "viewer_name": user["name"],
            "viewed_at": now_kst().strftime("%Y-%m-%d %H:%M"),
        }
    )


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
    _, cands, choose = _approvers(conn, user, "accom")

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
            "approvers": cands if choose else [],
        }
    )


@router.post("/accommodation")
async def mypage_accommodation_post(
    request: Request,
    category: str = Form(...),
    title: str = Form(...),
    description: str = Form(None),
    urgency: str = Form("normal"),
    approver_id: int = Form(0),
    user: dict = Depends(require_login),
    conn = Depends(get_db),
):
    emp_id = get_employee_id(conn, user["id"])
    if emp_id:
        book, lines, err = _pick(conn, user, "accom", approver_id)
        if err:
            return RedirectResponse(url=f"/mypage/accommodation?error={quote(err)}", status_code=303)
        content = f"유형 {category}\n\n{description or ''}"
        doc_id = open_doc(conn, user, book, "accom", f"편의지원 {user['name']} {title}", content, lines)
        conn.execute(
            """INSERT INTO accommodation_requests (employee_id, category, title, description, urgency, status, doc_id)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (emp_id, category, title, description or None, urgency, doc_id),
        )
        conn.commit()
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
    pw_required = request.query_params.get("pw_required") == "1"
    pw_changed = request.query_params.get("pw_changed") == "1"
    return templates.TemplateResponse(
        request=request, name="mypage/profile.html", context={
            "request": request,
            "page_title": "내 정보",
            "user_name": user["name"],
            "user": user_info,
            "employee": emp_info,
            "edit_mode": edit_mode,
            "error": error,
            "pw_required": pw_required,
            "pw_changed": pw_changed,
        }
    )


@router.get("/login-history", response_class=HTMLResponse)
async def mypage_login_history(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    acct = conn.execute("SELECT username FROM users WHERE id=?", (user["id"],)).fetchone()
    history = [dict(r) for r in conn.execute(
        "SELECT ip, ok, at FROM login_attempts WHERE username=? ORDER BY at DESC LIMIT 50",
        (acct["username"],)
    )]
    return templates.TemplateResponse(
        request=request, name="mypage/login_history.html", context={
            "request": request,
            "page_title": "로그인 이력",
            "history": history,
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
    if len(new_password) < 8:
        return RedirectResponse(url="/mypage/profile?error=pw_short", status_code=303)
    row = conn.execute(
        "SELECT password FROM users WHERE id=?", (user["id"],)
    ).fetchone()
    if not row or not verify_pw(current_password, row["password"]):
        return RedirectResponse(url="/mypage/profile?error=pw_wrong", status_code=303)
    if new_password == current_password:
        return RedirectResponse(url="/mypage/profile?error=pw_same", status_code=303)
    new_hash = hash_pw(new_password)
    conn.execute(
        "UPDATE users SET password=?, must_change_password=0 WHERE id=?", (new_hash, user["id"])
    )
    conn.commit()
    request.session.pop("pw_reset", None)
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
    emp = conn.execute(
        "SELECT id, name, company_id, bank_name, bank_account FROM employees WHERE user_id=?", (user["id"],)
    ).fetchone()
    conn.execute(
        """UPDATE employees SET phone=?, address=?, emergency_contact=?,
           bank_name=?, bank_account=? WHERE user_id=?""",
        (phone.strip(), address.strip(), emergency_contact.strip(),
         bank_name.strip(), bank_account.strip(), user["id"]),
    )
    # 급여 입금 계좌 변경은 횡령 경로이므로 이력 기록 후 담당자에게 통지
    if emp and (bank_name.strip(), bank_account.strip()) != (emp["bank_name"] or "", emp["bank_account"] or ""):
        after = f"{bank_name.strip()} {mask_acct(bank_account.strip())}"
        audit.log(conn, user["id"], "bank_account_change", "employee", emp["id"], emp["name"],
                  detail={"before": f"{emp['bank_name'] or ''} {mask_acct(emp['bank_account'])}", "after": after},
                  company_id=emp["company_id"], ip=get_client_ip(request))
        hr_ids = [h["id"] for h in hr_approvers(conn, emp["company_id"] or 0)]
        if hr_ids:
            create_bulk_notifications(conn, hr_ids, "근로자 급여 계좌 변경", f"{emp['name']} {after}",
                                      f"/payroll/{emp['id']}/info")
    conn.commit()
    return RedirectResponse(url="/mypage/profile", status_code=303)
