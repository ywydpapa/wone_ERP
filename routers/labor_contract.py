import hashlib
import json

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import (
    get_db, templates,
    require_client_with_company, require_client_hr_with_company, require_worker, require_staff,
)
from core.constants import COMPANY_INFO
from core.auth import verify_pw
from core.notification import create_notification
from core.rate_limit import get_client_ip
from core.tz import now_kst
from core import audit

router = APIRouter()

CONTRACT_FORM_FIELDS = (
    "kind", "has_term", "start_date", "end_date", "place", "duty",
    "work_days", "work_start", "work_end", "break_min", "weekly_hours",
    "daily_hours_json", "holidays", "wage_type", "base_pay", "allowances_json",
    "pay_day", "pay_method", "annual_leave", "insurance", "etc_terms",
)


def _latest(conn, employee_id):
    row = conn.execute(
        "SELECT * FROM labor_contracts WHERE employee_id=? ORDER BY version DESC LIMIT 1",
        (employee_id,),
    ).fetchone()
    return dict(row) if row else None


def _get(conn, contract_id):
    row = conn.execute("SELECT * FROM labor_contracts WHERE id=?", (contract_id,)).fetchone()
    return dict(row) if row else None


def _owns(contract, user):
    role = user["role"]
    if role == "client":
        return contract["company_id"] == user.get("company_id")
    if role == "worker":
        return contract["employee_id"] == user.get("employee_id")
    return False


def _company(conn, company_id):
    if not company_id:
        return {"name": COMPANY_INFO["name"], "representative": COMPANY_INFO["representative"],
                "business_no": COMPANY_INFO["biz_no"], "address": COMPANY_INFO["address"]}
    row = conn.execute(
        "SELECT name, representative, business_no, address FROM client_companies WHERE id=?", (company_id,)
    ).fetchone()
    return dict(row) if row else {}


def _safe_json(s):
    try:
        return json.loads(s) if s else []
    except ValueError:
        return []


def _doc_context(conn, contract):
    emp = conn.execute(
        "SELECT name, birth_date, address FROM employees WHERE id=?", (contract["employee_id"],)
    ).fetchone()
    return {
        "c": contract,
        "emp": dict(emp) if emp else {},
        "company": _company(conn, contract["company_id"]),
        "allowances": _safe_json(contract["allowances_json"]),
        "daily_hours": _safe_json(contract["daily_hours_json"]),
    }


def _render_body(conn, contract):
    return templates.get_template("common/contract_body.html").render(**_doc_context(conn, contract))


def _history(conn, employee_id):
    rows = conn.execute(
        "SELECT id, version, status, created_at FROM labor_contracts WHERE employee_id=? ORDER BY version DESC",
        (employee_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _detail_context(request, conn, contract, user, viewer):
    body_ok = None
    if contract["body_html"]:
        body_ok = hashlib.sha256(contract["body_html"].encode()).hexdigest() == contract["body_hash"]
        preview = contract["body_html"]
    else:
        preview = _render_body(conn, contract)

    employer_signer = conn.execute(
        "SELECT name FROM users WHERE id=?", (contract["employer_signed_by"],)
    ).fetchone() if contract["employer_signed_by"] else None

    emp = conn.execute(
        "SELECT name FROM employees WHERE id=?", (contract["employee_id"],)
    ).fetchone()

    latest = _latest(conn, contract["employee_id"])
    return {
        "request": request,
        "page_title": "근로계약서",
        "user_name": user["name"],
        "contract": contract,
        "employee_name": emp["name"] if emp else "",
        "preview": preview,
        "body_ok": body_ok,
        "signer_name": employer_signer["name"] if employer_signer else "",
        "history": _history(conn, contract["employee_id"]),
        "is_latest": latest and latest["id"] == contract["id"],
        "viewer": viewer,
        "msg": request.query_params.get("msg", ""),
        "error": request.query_params.get("error", ""),
    }


# 고객사 담당자 - 목록

@router.get("/client/labor-contracts", response_class=HTMLResponse)
async def contract_list(
    request: Request,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    company_id = user["company_id"]
    rows = conn.execute(
        """SELECT lc.*, e.name AS employee_name FROM labor_contracts lc
           JOIN employees e ON e.id = lc.employee_id
           WHERE lc.company_id=? AND lc.version = (
               SELECT MAX(version) FROM labor_contracts WHERE employee_id = lc.employee_id
           )
           ORDER BY e.name""",
        (company_id,),
    ).fetchall()
    contracts = [dict(r) for r in rows]
    contracted = {c["employee_id"] for c in contracts}
    workers = conn.execute(
        "SELECT id, name FROM employees WHERE company_id=? AND status='active' ORDER BY name", (company_id,)
    ).fetchall()
    no_contract = [dict(w) for w in workers if w["id"] not in contracted]

    return templates.TemplateResponse(
        request=request, name="client/contracts.html", context={
            "request": request,
            "page_title": "근로계약서",
            "user_name": user["name"],
            "contracts": contracts,
            "no_contract": no_contract,
        }
    )


@router.get("/client/labor-contracts/new", response_class=HTMLResponse)
async def contract_new_form(
    request: Request,
    employee_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    if not emp or emp["company_id"] != user["company_id"]:
        raise HTTPException(status_code=404)
    if _latest(conn, employee_id):
        raise HTTPException(status_code=400, detail="이미 작성된 계약서가 있습니다")

    company = _company(conn, user["company_id"])
    return templates.TemplateResponse(
        request=request, name="client/contract_form.html", context={
            "request": request,
            "page_title": "근로계약서 작성",
            "user_name": user["name"],
            "employee": dict(emp),
            "contract": None,
            "place_default": company.get("address", ""),
            "weekly_default": round(emp["monthly_work_hours"] / 4.345, 1) if emp["monthly_work_hours"] else 0,
        }
    )


@router.post("/client/labor-contracts")
async def contract_create(
    request: Request,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
    employee_id: int = Form(...),
    kind: str = Form("일반"),
    has_term: int = Form(0),
    start_date: str = Form(...),
    end_date: str = Form(""),
    place: str = Form(""),
    duty: str = Form(""),
    work_days: str = Form(""),
    work_start: str = Form(""),
    work_end: str = Form(""),
    break_min: int = Form(60),
    weekly_hours: float = Form(0),
    daily_hours_json: str = Form(""),
    holidays: str = Form("매주 일요일(주휴일)"),
    wage_type: str = Form("월급"),
    base_pay: int = Form(0),
    allowances_json: str = Form("[]"),
    pay_day: str = Form("매월 25일"),
    pay_method: str = Form("근로자 명의 계좌로 지급"),
    annual_leave: str = Form("근로기준법 제60조에 따라 부여"),
    insurance: str = Form("고용보험,산재보험,국민연금,건강보험"),
    etc_terms: str = Form(""),
):
    emp = conn.execute("SELECT company_id FROM employees WHERE id=?", (employee_id,)).fetchone()
    if not emp or emp["company_id"] != user["company_id"]:
        raise HTTPException(status_code=404)
    if _latest(conn, employee_id):
        raise HTTPException(status_code=400, detail="이미 작성된 계약서가 있습니다")

    new_id = conn.execute(
        """INSERT INTO labor_contracts
           (company_id, employee_id, version, kind, has_term, start_date, end_date, place, duty,
            work_days, work_start, work_end, break_min, weekly_hours, daily_hours_json, holidays,
            wage_type, base_pay, allowances_json, pay_day, pay_method, annual_leave, insurance,
            etc_terms, created_by)
           VALUES (?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user["company_id"], employee_id, kind, has_term, start_date, end_date, place, duty,
         work_days, work_start, work_end, break_min, weekly_hours, daily_hours_json, holidays,
         wage_type, base_pay, allowances_json, pay_day, pay_method, annual_leave, insurance,
         etc_terms, user["id"]),
    ).lastrowid
    audit.log(conn, user["id"], "contract_create", "labor_contract", new_id, "v1", company_id=user["company_id"])
    conn.commit()
    return RedirectResponse(url=f"/client/labor-contracts/{new_id}", status_code=303)


@router.get("/client/labor-contracts/{contract_id}/edit", response_class=HTMLResponse)
async def contract_edit_form(
    request: Request,
    contract_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    contract = _get(conn, contract_id)
    if not contract or contract["company_id"] != user["company_id"]:
        raise HTTPException(status_code=404)
    if contract["status"] != "draft":
        raise HTTPException(status_code=400, detail="발송 후에는 수정할 수 없습니다")

    emp = conn.execute("SELECT * FROM employees WHERE id=?", (contract["employee_id"],)).fetchone()
    return templates.TemplateResponse(
        request=request, name="client/contract_form.html", context={
            "request": request,
            "page_title": "근로계약서 수정",
            "user_name": user["name"],
            "employee": dict(emp) if emp else {},
            "contract": contract,
            "place_default": "",
        }
    )


@router.post("/client/labor-contracts/{contract_id}")
async def contract_update(
    request: Request,
    contract_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
    kind: str = Form("일반"),
    has_term: int = Form(0),
    start_date: str = Form(...),
    end_date: str = Form(""),
    place: str = Form(""),
    duty: str = Form(""),
    work_days: str = Form(""),
    work_start: str = Form(""),
    work_end: str = Form(""),
    break_min: int = Form(60),
    weekly_hours: float = Form(0),
    daily_hours_json: str = Form(""),
    holidays: str = Form("매주 일요일(주휴일)"),
    wage_type: str = Form("월급"),
    base_pay: int = Form(0),
    allowances_json: str = Form("[]"),
    pay_day: str = Form("매월 25일"),
    pay_method: str = Form("근로자 명의 계좌로 지급"),
    annual_leave: str = Form("근로기준법 제60조에 따라 부여"),
    insurance: str = Form("고용보험,산재보험,국민연금,건강보험"),
    etc_terms: str = Form(""),
):
    contract = _get(conn, contract_id)
    if not contract or contract["company_id"] != user["company_id"]:
        raise HTTPException(status_code=404)
    if contract["status"] != "draft":
        raise HTTPException(status_code=400, detail="발송 후에는 수정할 수 없습니다")

    conn.execute(
        """UPDATE labor_contracts SET
               kind=?, has_term=?, start_date=?, end_date=?, place=?, duty=?,
               work_days=?, work_start=?, work_end=?, break_min=?, weekly_hours=?, daily_hours_json=?,
               holidays=?, wage_type=?, base_pay=?, allowances_json=?, pay_day=?, pay_method=?,
               annual_leave=?, insurance=?, etc_terms=?, updated_at=datetime('now','localtime')
           WHERE id=?""",
        (kind, has_term, start_date, end_date, place, duty, work_days, work_start, work_end,
         break_min, weekly_hours, daily_hours_json, holidays, wage_type, base_pay, allowances_json,
         pay_day, pay_method, annual_leave, insurance, etc_terms, contract_id),
    )
    conn.commit()
    return RedirectResponse(url=f"/client/labor-contracts/{contract_id}", status_code=303)


@router.post("/client/labor-contracts/{contract_id}/revisions")
async def contract_revise(
    request: Request,
    contract_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    contract = _get(conn, contract_id)
    if not contract or contract["company_id"] != user["company_id"]:
        raise HTTPException(status_code=404)
    latest = _latest(conn, contract["employee_id"])
    if not latest or latest["id"] != contract_id or contract["status"] not in ("sent", "signed"):
        raise HTTPException(status_code=400, detail="최신 계약서만 새 버전으로 변경할 수 있습니다")

    cols = ", ".join(CONTRACT_FORM_FIELDS)
    new_id = conn.execute(
        f"""INSERT INTO labor_contracts (company_id, employee_id, version, prev_id, created_by, {cols})
            SELECT company_id, employee_id, version + 1, id, ?, {cols}
            FROM labor_contracts WHERE id=?""",
        (user["id"], contract_id),
    ).lastrowid
    audit.log(conn, user["id"], "contract_revise", "labor_contract", new_id,
               f"v{contract['version'] + 1}", company_id=user["company_id"])
    conn.commit()
    return RedirectResponse(url=f"/client/labor-contracts/{new_id}/edit", status_code=303)


@router.post("/client/labor-contracts/{contract_id}/signature")
async def contract_sign_employer(
    request: Request,
    contract_id: int,
    user: dict = Depends(require_client_hr_with_company),
    conn=Depends(get_db),
    password: str = Form(...),
    agree: int = Form(0),
):
    contract = _get(conn, contract_id)
    if not contract or contract["company_id"] != user["company_id"]:
        raise HTTPException(status_code=404)
    if contract["status"] != "draft":
        return RedirectResponse(url=f"/client/labor-contracts/{contract_id}?error=state", status_code=303)
    if not agree:
        return RedirectResponse(url=f"/client/labor-contracts/{contract_id}?error=agree", status_code=303)

    row = conn.execute("SELECT password FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row or not verify_pw(password, row["password"]):
        return RedirectResponse(url=f"/client/labor-contracts/{contract_id}?error=wrong_password", status_code=303)

    ip = get_client_ip(request)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    body_html = _render_body(conn, contract)
    body_hash = hashlib.sha256(body_html.encode()).hexdigest()
    conn.execute(
        """UPDATE labor_contracts SET status='sent', employer_signed_by=?, employer_signed_at=?,
               employer_sign_ip=?, body_html=?, body_hash=?, updated_at=datetime('now','localtime')
           WHERE id=?""",
        (user["id"], now, ip, body_html, body_hash, contract_id),
    )
    audit.log(conn, user["id"], "contract_send", "labor_contract", contract_id,
               f"v{contract['version']}", company_id=user["company_id"], ip=ip)

    emp = conn.execute("SELECT user_id FROM employees WHERE id=?", (contract["employee_id"],)).fetchone()
    if emp and emp["user_id"]:
        label = "근로계약서가 도착했습니다" if contract["version"] == 1 else "변경된 근로계약서가 도착했습니다"
        create_notification(conn, emp["user_id"], label, "서명이 필요합니다", f"/contracts/{contract_id}")

    conn.commit()
    return RedirectResponse(url=f"/client/labor-contracts/{contract_id}?msg=sent", status_code=303)


def _contract_detail(conn, user, contract_id):
    contract = _get(conn, contract_id)
    if not contract or not _owns(contract, user):
        raise HTTPException(status_code=404)
    return contract


def _employee_name(conn, employee_id):
    row = conn.execute("SELECT name FROM employees WHERE id=?", (employee_id,)).fetchone()
    return row["name"] if row else ""


@router.get("/client/labor-contracts/{contract_id}", response_class=HTMLResponse)
async def contract_detail_client(
    request: Request,
    contract_id: int,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
):
    contract = _contract_detail(conn, user, contract_id)
    return templates.TemplateResponse(
        request=request, name="client/contract_detail.html",
        context=_detail_context(request, conn, contract, user, "client"),
    )


@router.get("/client/labor-contracts/{contract_id}/print", response_class=HTMLResponse)
async def contract_print_client(
    request: Request,
    contract_id: int,
    user: dict = Depends(require_client_with_company()),
    conn=Depends(get_db),
    reason: str = Depends(audit.require_reason),
):
    contract = _contract_detail(conn, user, contract_id)
    if not contract["body_html"]:
        raise HTTPException(status_code=400, detail="발송 전에는 인쇄할 수 없습니다")
    audit.log_pii_export(conn, user, request, reason, "근로계약서 인쇄", 1,
                          company_id=contract["company_id"], action="print")
    return templates.TemplateResponse(
        request=request, name="common/contract_print.html",
        context={
            "request": request, "contract": contract,
            "employee_name": _employee_name(conn, contract["employee_id"]),
            "viewer_name": user["name"], "viewed_at": now_kst().strftime("%Y-%m-%d %H:%M"),
        },
    )


# 근로자 - 목록/열람/서명

@router.get("/contracts", response_class=HTMLResponse)
async def worker_contract_list(
    request: Request,
    user: dict = Depends(require_worker),
    conn=Depends(get_db),
):
    rows = conn.execute(
        "SELECT * FROM labor_contracts WHERE employee_id=? ORDER BY version DESC", (user["employee_id"],)
    ).fetchall()
    return templates.TemplateResponse(
        request=request, name="worker/contracts.html", context={
            "request": request,
            "page_title": "근로계약서",
            "user_name": user["name"],
            "contracts": [dict(r) for r in rows],
        }
    )


def _mark_delivered(conn, contract):
    if contract["status"] != "draft" and not contract["delivered_at"]:
        now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE labor_contracts SET delivered_at=? WHERE id=?", (now, contract["id"]))
        conn.commit()
        contract["delivered_at"] = now


@router.get("/contracts/{contract_id}", response_class=HTMLResponse)
async def contract_detail_worker(
    request: Request,
    contract_id: int,
    user: dict = Depends(require_worker),
    conn=Depends(get_db),
):
    contract = _contract_detail(conn, user, contract_id)
    _mark_delivered(conn, contract)
    return templates.TemplateResponse(
        request=request, name="client/contract_detail.html",
        context=_detail_context(request, conn, contract, user, "worker"),
    )


@router.get("/contracts/{contract_id}/print", response_class=HTMLResponse)
async def contract_print_worker(
    request: Request,
    contract_id: int,
    user: dict = Depends(require_worker),
    conn=Depends(get_db),
):
    contract = _contract_detail(conn, user, contract_id)
    if not contract["body_html"]:
        raise HTTPException(status_code=400, detail="발송 전에는 인쇄할 수 없습니다")
    _mark_delivered(conn, contract)
    return templates.TemplateResponse(
        request=request, name="common/contract_print.html",
        context={
            "request": request, "contract": contract,
            "employee_name": _employee_name(conn, contract["employee_id"]),
            "viewer_name": user["name"], "viewed_at": now_kst().strftime("%Y-%m-%d %H:%M"),
        },
    )


@router.post("/contracts/{contract_id}/signature")
async def contract_sign_worker(
    request: Request,
    contract_id: int,
    user: dict = Depends(require_worker),
    conn=Depends(get_db),
    password: str = Form(...),
    sign_name: str = Form(...),
    agree: int = Form(0),
):
    contract = _get(conn, contract_id)
    if not contract or not _owns(contract, user):
        raise HTTPException(status_code=404)
    if contract["status"] != "sent":
        return RedirectResponse(url=f"/contracts/{contract_id}?error=state", status_code=303)
    if not agree:
        return RedirectResponse(url=f"/contracts/{contract_id}?error=agree", status_code=303)
    if hashlib.sha256(contract["body_html"].encode()).hexdigest() != contract["body_hash"]:
        return RedirectResponse(url=f"/contracts/{contract_id}?error=tampered", status_code=303)

    emp = conn.execute("SELECT name FROM employees WHERE id=?", (contract["employee_id"],)).fetchone()
    if sign_name.strip() != (emp["name"] if emp else ""):
        return RedirectResponse(url=f"/contracts/{contract_id}?error=name_mismatch", status_code=303)

    row = conn.execute("SELECT password FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row or not verify_pw(password, row["password"]):
        return RedirectResponse(url=f"/contracts/{contract_id}?error=wrong_password", status_code=303)

    ip = get_client_ip(request)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """UPDATE labor_contracts SET status='signed', worker_signed_at=?, worker_sign_ip=?,
               worker_sign_name=?, updated_at=datetime('now','localtime') WHERE id=?""",
        (now, ip, sign_name.strip(), contract_id),
    )
    audit.log(conn, user["id"], "contract_sign", "labor_contract", contract_id,
               f"v{contract['version']}", company_id=contract["company_id"], ip=ip)
    conn.commit()
    return RedirectResponse(url=f"/contracts/{contract_id}?msg=signed", status_code=303)


# 플랫폼 스태프는 지휘명령권이 없어 계약 본문 미열람. 상태 메타데이터만

@router.get("/platform/contracts", response_class=HTMLResponse)
async def staff_contract_list(
    request: Request,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    rows = conn.execute(
        """SELECT lc.id, lc.version, lc.status, lc.has_term, lc.start_date, lc.end_date,
                  e.name AS employee_name, cc.name AS company_name FROM labor_contracts lc
           JOIN employees e ON e.id = lc.employee_id
           LEFT JOIN client_companies cc ON cc.id = lc.company_id
           WHERE lc.version = (SELECT MAX(version) FROM labor_contracts WHERE employee_id = lc.employee_id)
           ORDER BY cc.name, e.name"""
    ).fetchall()
    return templates.TemplateResponse(
        request=request, name="client/contracts.html", context={
            "request": request,
            "page_title": "근로계약서",
            "user_name": user["name"],
            "contracts": [dict(r) for r in rows],
            "no_contract": [],
            "staff_view": True,
        }
    )
