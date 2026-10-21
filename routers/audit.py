import csv
import io
import json
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from core.books import book_of
from core.deps import get_db, require_login, templates
from core.export import esc_cell
from core.tz import today_kst

router = APIRouter()

PER_PAGE = 50

ACTIONS = {
    "login": "로그인", "login_fail": "로그인 실패", "login_lock": "계정 잠금", "logout": "로그아웃",
    "post": "전표 전기", "reverse": "역분개", "slip_update": "전표 수정", "slip_delete": "전표 삭제",
    "invoice_create": "세금계산서 발행", "invoice_amend": "수정세금계산서", "invoice_import": "홈택스 불러오기",
    "close": "월마감", "reopen": "월마감 취소", "fiscal_close": "회기 마감", "fiscal_reopen": "회기 마감 취소",
    "gr_confirm": "입고", "ship_confirm": "출고", "stock_adjust": "재고조정",
    "gr_return": "구매 반품", "ship_return": "판매 반품", "return_cancel": "반품 취소",
    "payroll_confirm": "급여 확정", "payroll_edit": "급여 수정", "payroll_transfer": "급여 이체파일",
    "payroll_pay": "급여 지급", "payroll_reopen": "급여확정 취소",
    "employee_create": "근로자 등록", "employee_update": "근로자 수정", "employee_resign": "퇴사 처리",
    "partner_create": "거래처 등록", "partner_update": "거래처 수정", "partner_merge": "거래처 통합",
    "settle_create": "수금/지급 등록", "settle_cancel": "수금/지급 취소", "bank_post": "은행거래 전표",
    "perm_update": "권한 변경", "role_change": "역할 변경", "user_unlock": "잠금 해제", "backup": "백업",
    "doc_submit": "결재 상신", "doc_approve": "결재 승인", "doc_reject": "결재 반려", "doc_withdraw": "결재 철회",
    "po_approve": "발주 승인", "po_reject": "발주 반려", "wo_release": "작업 착수", "wo_cancel": "작업 취소",
    "att_edit": "근태 수정", "att_close": "근태 마감", "att_reopen": "근태 마감 취소",
    "leave_approve": "휴가 승인", "leave_reject": "휴가 반려", "leave_cancel": "휴가 취소",
    "rate_update": "보험요율 변경", "company_update": "고객사 수정",
}

TARGET_TYPES = {
    "user": "사용자", "slip": "전표", "invoice": "세금계산서", "closing": "월마감", "fiscal": "회기",
    "gr": "입고", "shipment": "출고", "stock_adj": "재고조정", "payslip": "급여", "employee": "근로자",
    "partner": "거래처", "settlement": "수금/지급", "bank_txn": "은행거래", "backup": "백업",
    "doc": "결재문서", "po": "발주", "work_order": "작업지시", "attendance": "근태", "leave": "휴가",
    "rate": "보험요율", "company": "고객사",
}


def audit_scope(request: Request, conn=Depends(get_db)):
    u = require_login(request)
    if u["role"] == "platform_staff":
        return {**u, "book": None}
    if u["role"] == "client":
        book = book_of(conn, u)
        if book is not None:
            return {**u, "book": book}
    raise HTTPException(status_code=403)


def _period(start, end):
    if not end:
        end = today_kst().isoformat()
    if not start:
        start = (today_kst() - timedelta(days=6)).isoformat()
    return start, end


def _filter(book, start, end, user, action, target_type, q):
    where = "WHERE at >= ? AND at <= ?"
    params = [f"{start} 00:00:00", f"{end} 23:59:59"]
    if book is not None:
        where += " AND company_id=?"
        params.append(book)
    if user:
        where += " AND user_name LIKE ?"
        params.append(f"%{user}%")
    if action:
        where += " AND action LIKE ?"
        params.append(f"{action}%")
    if target_type:
        where += " AND target_type=?"
        params.append(target_type)
    if q:
        where += " AND summary LIKE ?"
        params.append(f"%{q}%")
    return where, params


def _detail_rows(detail):
    return [(k, v[0], v[1]) for k, v in json.loads(detail).items()] if detail else []


AUDIT_SORTS = {"at": "at", "user": "user_name", "role": "role", "action": "action", "target": "target_type"}


@router.get("/audit", response_class=HTMLResponse)
async def audit_list(request: Request, start: str = "", end: str = "", user: str = "", action: str = "",
                     target_type: str = "", q: str = "", page: int = 1, sort: str = "", dir: str = "",
                     u: dict = Depends(audit_scope), conn=Depends(get_db)):
    start, end = _period(start, end)
    where, params = _filter(u["book"], start, end, user, action, target_type, q)

    total = conn.execute(f"SELECT COUNT(*) FROM audit_logs {where}", params).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    order = AUDIT_SORTS.get(sort)
    order_sql = f"ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, id DESC" if order else "ORDER BY at DESC, id DESC"
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM audit_logs {where} {order_sql} LIMIT {PER_PAGE} OFFSET {(page-1)*PER_PAGE}",
        params,
    ).fetchall()]
    for r in rows:
        r["action_label"] = ACTIONS.get(r["action"], r["action"])
        r["target_label"] = TARGET_TYPES.get(r["target_type"], r["target_type"] or "")
        r["detail_rows"] = _detail_rows(r["detail"])

    return templates.TemplateResponse(request=request, name="audit/audit_list.html", context={
        "request": request, "page_title": "감사 로그", "user_name": u["name"],
        "rows": rows, "start": start, "end": end, "user": user, "action": action,
        "target_type": target_type, "q": q, "actions": ACTIONS, "target_types": TARGET_TYPES,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/audit?start={start}&end={end}&user={quote(user)}&action={action}"
                    f"&target_type={target_type}&q={quote(q)}&sort={sort}&dir={dir}",
        "sort": sort, "dir": dir,
    })


@router.get("/audit/csv")
async def audit_csv(start: str = "", end: str = "", user: str = "", action: str = "",
                    target_type: str = "", q: str = "",
                    u: dict = Depends(audit_scope), conn=Depends(get_db)):
    start, end = _period(start, end)
    where, params = _filter(u["book"], start, end, user, action, target_type, q)
    rows = conn.execute(f"SELECT * FROM audit_logs {where} ORDER BY at DESC, id DESC", params).fetchall()

    buf = io.StringIO()
    buf.write('﻿')
    writer = csv.writer(buf)
    writer.writerow(["일시", "사용자", "역할", "구분", "대상", "요약", "IP", "상세"])
    for r in rows:
        writer.writerow([esc_cell(v) for v in [
            r["at"], r["user_name"] or "", r["role"] or "", ACTIONS.get(r["action"], r["action"]),
            TARGET_TYPES.get(r["target_type"], r["target_type"] or ""), r["summary"], r["ip"] or "",
            r["detail"] or "",
        ]])

    buf.seek(0)
    fname = today_kst().strftime("audit_%Y%m%d.csv")
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )
