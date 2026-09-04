import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from core.tz import today_kst
from core.db import with_status_meta
from core.deps import get_db, require_login, require_staff, templates
from core.constants import ERP_DOC_TYPES, ERP_REDIRECTS, ERP_DOC_TYPE_LABELS

router = APIRouter()

def _erp_docs_for(conn, dtype):
    return with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type=? ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 WHEN 'wait' THEN 2 ELSE 3 END, id DESC",
        (dtype,)
    ).fetchall())


def _module_dashboard(request, u, conn, doc_type, template_name, page_title, stat_queries):
    docs = _erp_docs_for(conn, doc_type)
    alerts = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type=? AND status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3",
        (doc_type,)
    ).fetchall())
    ctx = {
        "request": request,
        "page_title": page_title,
        "docs": docs,
        "alerts": alerts,
        "user_name": u["user_name"],
    }
    for var_name, sql in stat_queries:
        ctx[var_name] = conn.execute(sql).fetchone()[0]
    return templates.TemplateResponse(request=request, name=template_name, context=ctx)


@router.get("/erp_dash", response_class=HTMLResponse)
async def erp_dash(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    today = today_kst().isoformat()
    uid = u["user_id"]
    role = u.get("user_role", "")
    if role == "platform_staff":
        counts = {r["doc_type"]: r["cnt"] for r in [
            dict(r) for r in conn.execute(
                "SELECT doc_type, COUNT(*) AS cnt FROM erp_docs GROUP BY doc_type"
            ).fetchall()
        ]}
        recent = with_status_meta(conn.execute("SELECT * FROM erp_docs ORDER BY id DESC LIMIT 5").fetchall())
    else:
        counts = {r["doc_type"]: r["cnt"] for r in [
            dict(r) for r in conn.execute(
                "SELECT doc_type, COUNT(*) AS cnt FROM erp_docs WHERE user_id=? GROUP BY doc_type", (uid,)
            ).fetchall()
        ]}
        recent = with_status_meta(conn.execute("SELECT * FROM erp_docs WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,)).fetchall())
    today_jobs = with_status_meta(conn.execute(
        "SELECT * FROM jobs WHERE user_id=? AND work_date=? AND status != 'trash' ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 ELSE 2 END, id",
        (uid, today)
    ).fetchall())
    return templates.TemplateResponse(
        request=request, name="erp/erp_dash.html", context={
            "request": request, "page_title": "업무 대시보드",
            "doc_counts": counts, "recent_docs": recent,
            "user_name": u["user_name"],
            "today_jobs": today_jobs,
        }
    )


@router.get("/erp_hr", response_class=HTMLResponse)
async def erp_hr(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    leave_count = conn.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE doc_type='hr_task' AND title LIKE '%휴가%'"
    ).fetchone()[0]
    docs = _erp_docs_for(conn, "hr_task")
    alerts = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='hr_task' AND status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/erp_hr.html", context={
        "request": request, "page_title": "인사관리 대시보드",
        "docs": docs,
        "alerts": alerts,
        "user_name": u["user_name"],
        "user_count": user_count,
        "leave_count": leave_count,
    })


@router.get("/erp_fa", response_class=HTMLResponse)
async def erp_fa(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='expense' ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 WHEN 'wait' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END, id DESC",
    ).fetchall())
    alert_rows = with_status_meta(conn.execute(
        """SELECT * FROM erp_docs
           WHERE doc_type IN ('expense', 'po')
           AND status IN ('urgent', 'wait', 'pending', 'progress')
           ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 WHEN 'wait' THEN 2 ELSE 3 END,
                    id DESC
           LIMIT 6""",
    ).fetchall())
    expense_done_count = conn.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE doc_type='expense' AND status IN ('done','approved')"
    ).fetchone()[0]
    expense_pending_count = conn.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE doc_type='expense' AND status IN ('wait','pending','urgent')"
    ).fetchone()[0]
    po_pending_count = conn.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE doc_type='po' AND status IN ('wait','pending','urgent','progress')"
    ).fetchone()[0]
    return templates.TemplateResponse(request=request, name="erp/erp_fa.html", context={
        "request": request, "page_title": "자금관리 대시보드",
        "docs": docs,
        "alerts": alert_rows,
        "expense_done_count": expense_done_count,
        "expense_pending_count": expense_pending_count,
        "po_pending_count": po_pending_count,
        "user_name": u["user_name"],
    })


@router.get("/erp_scrm", response_class=HTMLResponse)
async def erp_scrm(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    return _module_dashboard(request, u, conn, "activity", "erp/erp_scrm.html", "영업/고객관리 대시보드", [
        ("activity_count",    "SELECT COUNT(*) FROM erp_docs WHERE doc_type='activity'"),
        ("sales_leads_count", "SELECT COUNT(*) FROM erp_docs WHERE doc_type='activity' AND status IN ('progress','wait')"),
        ("voc_count",         "SELECT COUNT(*) FROM erp_docs WHERE doc_type='activity' AND status='urgent'"),
    ])


@router.get("/erp_purch", response_class=HTMLResponse)
async def erp_purch(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    return _module_dashboard(request, u, conn, "po", "erp/erp_purch.html", "구매관리 대시보드", [
        ("po_total_count",      "SELECT COUNT(*) FROM erp_docs WHERE doc_type='po'"),
        ("po_inprogress_count", "SELECT COUNT(*) FROM erp_docs WHERE doc_type='po' AND status IN ('wait','pending','urgent','progress')"),
        ("delayed_count",       "SELECT COUNT(*) FROM erp_docs WHERE doc_type='po' AND status='urgent'"),
    ])


@router.get("/erp_inventory", response_class=HTMLResponse)
async def erp_inventory(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    return _module_dashboard(request, u, conn, "stock_move", "erp/erp_inventory.html", "재고관리 대시보드", [
        ("stock_move_count", "SELECT COUNT(*) FROM erp_docs WHERE doc_type='stock_move'"),
        ("outbound_count",   "SELECT COUNT(*) FROM erp_docs WHERE doc_type='stock_move' AND status='done'"),
        ("low_stock_count",  "SELECT COUNT(*) FROM erp_docs WHERE doc_type='stock_move' AND status='urgent'"),
    ])


@router.get("/erp_product", response_class=HTMLResponse)
async def erp_product(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    return _module_dashboard(request, u, conn, "work_order", "erp/erp_product.html", "생산관리 대시보드", [
        ("work_order_count",           "SELECT COUNT(*) FROM erp_docs WHERE doc_type='work_order'"),
        ("production_inprogress_count","SELECT COUNT(*) FROM erp_docs WHERE doc_type='work_order' AND status IN ('progress','wait')"),
        ("equipment_alert_count",      "SELECT COUNT(*) FROM erp_docs WHERE doc_type='work_order' AND status='urgent'"),
    ])


@router.get("/erp_groupware", response_class=HTMLResponse)
async def erp_groupware(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    uid = u["user_id"]
    today = today_kst().isoformat()
    unread_mail = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE user_id=? AND is_read=0 AND direction='in'", (uid,)
    ).fetchone()[0]
    today_jobs = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE user_id=? AND work_date=?", (uid, today)
    ).fetchone()[0]
    pending_docs = conn.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE status IN ('wait','pending','urgent')"
    ).fetchone()[0]
    notices = [dict(r) for r in conn.execute(
        "SELECT id, category, title, author, dept, created_at FROM posts "
        "WHERE category IN ('notice', 'general') ORDER BY id DESC LIMIT 5"
    ).fetchall()]
    alerts = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/erp_groupware.html", context={
        "request": request, "page_title": "사내 그룹웨어",
        "docs": _erp_docs_for(conn, "draft"),
        "user_name": u["user_name"],
        "unread_mail": unread_mail,
        "today_jobs": today_jobs,
        "pending_docs": pending_docs,
        "notices": notices,
        "alerts": alerts,
    })


for _route_name, (_dtype, _dlabel) in ERP_DOC_TYPES.items():
    def _make_handler(__dtype=_dtype, __dlabel=_dlabel):
        async def handler(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
            uid = u["user_id"]
            try:
                users = [dict(u2) for u2 in conn.execute(
                    "SELECT id, name, dept, position FROM users WHERE id != ? ORDER BY dept, name", (uid,)
                ).fetchall()]
            except Exception:
                users = [dict(u2) for u2 in conn.execute(
                    "SELECT id, name, dept FROM users WHERE id != ? ORDER BY dept, name", (uid,)
                ).fetchall()]
            try:
                dt_row = conn.execute(
                    "SELECT form_schema FROM document_types WHERE name=?", (__dtype,)
                ).fetchone()
                form_schema = json.loads(dt_row["form_schema"]) if dt_row and dt_row["form_schema"] else {}
            except Exception:
                form_schema = {}
            return templates.TemplateResponse(
                request=request, name="erp/erp_form.html", context={
                    "request": request, "page_title": __dlabel,
                    "doc_type": __dtype, "back_url": ERP_REDIRECTS[__dtype],
                    "user_name": u["user_name"],
                    "users": users,
                    "form_schema": form_schema,
                }
            )
        return handler
    router.add_api_route(f"/{_route_name}", _make_handler(), methods=["GET"], response_class=HTMLResponse)


@router.get("/leave_approvals", response_class=HTMLResponse)
async def leave_approvals(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='hr_task' AND title LIKE '%휴가%' ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/leave_approvals.html", context={
        "request": request, "page_title": "휴가 승인",
        "user_name": u["user_name"], "docs": docs,
        "role": request.session.get("user_role", ""),
    })


@router.get("/recruitment_status", response_class=HTMLResponse)
async def recruitment_status(request: Request, u: dict = Depends(require_staff)):
    return templates.TemplateResponse(request=request, name="erp/recruitment_status.html", context={
        "request": request, "page_title": "채용 현황",
        "user_name": u["user_name"], "postings": [],
    })


@router.get("/outflow_list", response_class=HTMLResponse)
async def outflow_list(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='expense' AND status IN ('done','approved') ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "출금 완료 내역",
        "subtitle": "처리 완료된 지출 내역입니다.",
        "user_name": u["user_name"], "docs": docs,
    })


@router.get("/pending_payments", response_class=HTMLResponse)
async def pending_payments(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='expense' AND status IN ('wait','pending','urgent') ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "미결제 내역",
        "subtitle": "처리 대기 중인 지출 요청입니다.",
        "user_name": u["user_name"], "docs": docs,
    })


@router.get("/production_status", response_class=HTMLResponse)
async def production_status(request: Request, all: int = 0, u: dict = Depends(require_staff), conn = Depends(get_db)):
    if all == 1:
        query = "SELECT * FROM erp_docs WHERE doc_type='work_order' ORDER BY id DESC"
    else:
        query = "SELECT * FROM erp_docs WHERE doc_type='work_order' AND status IN ('progress','wait') ORDER BY id DESC"
    docs = with_status_meta(conn.execute(query).fetchall())
    if all == 1:
        page_title = "전체 작업지시"
        subtitle = "전체 작업 지시 목록입니다."
    else:
        page_title = "작업 진행 현황"
        subtitle = "진행 중이거나 대기 중인 작업 지시입니다."
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": page_title,
        "subtitle": subtitle,
        "user_name": u["user_name"], "docs": docs,
        "back_url": "/erp_product", "back_label": "생산관리",
    })


@router.get("/equipment_alerts", response_class=HTMLResponse)
async def equipment_alerts(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='work_order' AND status='urgent' ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "생산 긴급 알림",
        "subtitle": "긴급 처리가 필요한 작업 지시입니다.",
        "user_name": u["user_name"], "docs": docs,
        "back_url": "/erp_product", "back_label": "생산관리",
    })


@router.get("/po_status", response_class=HTMLResponse)
async def po_status(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='po' ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "발주 현황",
        "subtitle": "전체 발주서 목록입니다.",
        "user_name": u["user_name"], "docs": docs,
        "back_url": "/erp_purch", "back_label": "구매관리",
    })


@router.get("/delayed_delivery", response_class=HTMLResponse)
async def delayed_delivery(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='po' AND status='urgent' ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "납기 지연",
        "subtitle": "납기가 지연되어 긴급 확인이 필요한 발주입니다.",
        "user_name": u["user_name"], "docs": docs,
        "back_url": "/erp_purch", "back_label": "구매관리",
    })


@router.get("/po_pending", response_class=HTMLResponse)
async def po_pending(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='po' AND status IN ('wait','pending','urgent','progress') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 WHEN 'wait' THEN 2 ELSE 3 END, id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "발주 진행 현황",
        "subtitle": "진행 중인 발주 요청 목록입니다.",
        "user_name": u["user_name"], "docs": docs,
        "back_url": "/erp_purch", "back_label": "구매관리",
    })


@router.get("/outbound_status", response_class=HTMLResponse)
async def outbound_status(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='stock_move' ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "입출고 현황",
        "subtitle": "전체 입출고 등록 내역입니다.",
        "user_name": u["user_name"], "docs": docs,
        "back_url": "/erp_inventory", "back_label": "재고관리",
    })


@router.get("/low_stock_alerts", response_class=HTMLResponse)
async def low_stock_alerts(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='stock_move' AND status='urgent' ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "재고 부족 알림",
        "subtitle": "긴급 보충이 필요한 재고 항목입니다.",
        "user_name": u["user_name"], "docs": docs,
        "back_url": "/erp_inventory", "back_label": "재고관리",
    })


@router.get("/sales_leads", response_class=HTMLResponse)
async def sales_leads(request: Request, all: int = 0, u: dict = Depends(require_staff), conn = Depends(get_db)):
    if all == 1:
        query = "SELECT * FROM erp_docs WHERE doc_type='activity' ORDER BY id DESC"
    else:
        query = "SELECT * FROM erp_docs WHERE doc_type='activity' AND status IN ('progress','wait') ORDER BY id DESC"
    docs = with_status_meta(conn.execute(query).fetchall())
    if all == 1:
        page_title = "전체 영업 활동"
        subtitle = "전체 영업 활동 목록입니다."
    else:
        page_title = "영업 기회"
        subtitle = "진행 중인 영업 활동입니다."
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": page_title,
        "subtitle": subtitle,
        "user_name": u["user_name"], "docs": docs,
        "back_url": "/erp_scrm", "back_label": "영업/고객관리",
    })


@router.get("/voc_list", response_class=HTMLResponse)
async def voc_list(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='activity' AND status='urgent' ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "고객 VOC",
        "subtitle": "긴급 대응이 필요한 고객 요청입니다.",
        "user_name": u["user_name"], "docs": docs,
        "back_url": "/erp_scrm", "back_label": "영업/고객관리",
    })


@router.get("/approval_pending", response_class=HTMLResponse)
async def approval_pending(request: Request, u: dict = Depends(require_staff), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE status IN ('wait','pending','urgent') ORDER BY CASE status WHEN 'urgent' THEN 0 ELSE 1 END, id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/approval_pending.html", context={
        "request": request, "page_title": "결재 대기",
        "user_name": u["user_name"], "docs": docs,
        "role": request.session.get("user_role", ""),
        "labels": ERP_DOC_TYPE_LABELS,
    })
