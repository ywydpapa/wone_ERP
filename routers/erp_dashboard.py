import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from core.tz import today_kst
from core.db import with_status_meta
from core.deps import get_db, require_login, templates
from core.constants import ERP_DOC_TYPES, ERP_REDIRECTS, ERP_DOC_TYPE_LABELS, ERP_LEGACY_REDIRECTS
from routers.erp_purchase import PO_STATUS, PO_STATUS_CLASS
from routers.erp_sales import QT_STATUS, QT_STATUS_CLASS, SO_STATUS, SO_STATUS_CLASS
from routers.erp_production import WO_STATUS, WO_STATUS_CLASS

router = APIRouter()


def _stamp_date(rows):
    for r in rows:
        r['created_date'] = r['created_at'][:10] if r.get('created_at') else ''
    return rows


def _erp_docs_for(conn, dtype):
    return with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type=? ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 WHEN 'wait' THEN 2 ELSE 3 END, id DESC",
        (dtype,)
    ).fetchall())


def _module_dashboard(request, u, conn, doc_type, template_name, page_title, stat_queries):
    docs = _erp_docs_for(conn, doc_type)
    alerts = _stamp_date(with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type=? AND status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3",
        (doc_type,)
    ).fetchall()))
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
async def erp_hr(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    leave_count = conn.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE doc_type='hr_task' AND title LIKE '%휴가%'"
    ).fetchone()[0]
    docs = _erp_docs_for(conn, "hr_task")
    alerts = _stamp_date(with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='hr_task' AND status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3"
    ).fetchall()))
    return templates.TemplateResponse(request=request, name="erp/erp_hr.html", context={
        "request": request, "page_title": "인사관리 대시보드",
        "docs": docs,
        "alerts": alerts,
        "user_name": u["user_name"],
        "user_count": user_count,
        "leave_count": leave_count,
    })


@router.get("/erp_fa", response_class=HTMLResponse)
async def erp_fa(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='expense' ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'progress' THEN 1 WHEN 'wait' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END, id DESC",
    ).fetchall())
    alert_rows = _stamp_date(with_status_meta(conn.execute(
        """SELECT * FROM erp_docs
           WHERE doc_type IN ('expense', 'po')
           AND status IN ('urgent', 'wait', 'pending', 'progress')
           ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 WHEN 'wait' THEN 2 ELSE 3 END,
                    id DESC
           LIMIT 6""",
    ).fetchall()))
    expense_done_count = conn.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE doc_type='expense' AND status IN ('done','approved')"
    ).fetchone()[0]
    expense_pending_count = conn.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE doc_type='expense' AND status IN ('wait','pending','urgent')"
    ).fetchone()[0]
    tax_invoice_count = conn.execute(
        "SELECT COUNT(*) FROM erp_docs WHERE doc_number LIKE 'SAL-%' OR (doc_number LIKE 'EXP-%' AND title LIKE '입고 전표%')"
    ).fetchone()[0]

    cur_month = today_kst().strftime("%Y-%m")
    monthly_rev = conn.execute(
        """SELECT COALESCE(SUM(sl.credit),0) FROM slip_lines sl
           JOIN erp_docs ed ON sl.doc_id=ed.id
           WHERE sl.account_code LIKE '4%' AND sl.credit > 0 AND ed.slip_date LIKE ?""",
        (f"{cur_month}%",),
    ).fetchone()[0]
    monthly_exp = conn.execute(
        """SELECT COALESCE(SUM(sl.debit),0) FROM slip_lines sl
           JOIN erp_docs ed ON sl.doc_id=ed.id
           WHERE (sl.account_code LIKE '5%' OR sl.account_code LIKE '6%'
                  OR sl.account_code LIKE '7%' OR sl.account_code LIKE '8%')
             AND sl.debit > 0 AND ed.slip_date LIKE ?""",
        (f"{cur_month}%",),
    ).fetchone()[0]

    return templates.TemplateResponse(request=request, name="erp/erp_fa.html", context={
        "request": request, "page_title": "자금관리 대시보드",
        "docs": docs,
        "alerts": alert_rows,
        "expense_done_count": expense_done_count,
        "expense_pending_count": expense_pending_count,
        "tax_invoice_count": tax_invoice_count,
        "monthly_profit": monthly_rev - monthly_exp,
        "user_name": u["user_name"],
    })


@router.get("/erp_scrm", response_class=HTMLResponse)
async def erp_scrm(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    today = today_kst().isoformat()
    qt_total = conn.execute("SELECT COUNT(*) FROM quotations").fetchone()[0]
    so_active = conn.execute(
        "SELECT COUNT(*) FROM sales_orders WHERE status IN ('confirmed','picking')"
    ).fetchone()[0]
    so_shipped = conn.execute(
        "SELECT COUNT(*) FROM sales_orders WHERE status='shipped'"
    ).fetchone()[0]
    recent_quotes = [dict(r) for r in conn.execute(
        """SELECT q.*, c.name as customer_name FROM quotations q
           LEFT JOIN client_companies c ON q.customer_id=c.id
           ORDER BY q.id DESC LIMIT 5"""
    ).fetchall()]
    for r in recent_quotes:
        r["status_label"] = QT_STATUS.get(r["status"], r["status"])
        r["status_class"] = QT_STATUS_CLASS.get(r["status"], "")

    active_sos = [dict(r) for r in conn.execute(
        """SELECT so.*, c.name as customer_name FROM sales_orders so
           LEFT JOIN client_companies c ON so.customer_id=c.id
           WHERE so.status IN ('confirmed','picking')
           ORDER BY so.id DESC LIMIT 5"""
    ).fetchall()]
    for r in active_sos:
        r["status_label"] = SO_STATUS.get(r["status"], r["status"])
        r["status_class"] = SO_STATUS_CLASS.get(r["status"], "")

    alerts_rows = []
    overdue = conn.execute(
        """SELECT so.id, so.so_number, c.name as customer_name, so.delivery_date, so.status
           FROM sales_orders so
           LEFT JOIN client_companies c ON so.customer_id=c.id
           WHERE so.status IN ('confirmed','picking') AND so.delivery_date < ? AND so.delivery_date != ''
           ORDER BY so.delivery_date LIMIT 3""", (today,)
    ).fetchall()
    for row in overdue:
        r = dict(row)
        alerts_rows.append({
            "id": r["id"], "title": f"{r['so_number']} {r['customer_name'] or ''} 납기 지연",
            "status": "urgent", "status_class": "status-badge status-reject",
            "status_label": "납기 지연", "created_at": r["delivery_date"],
        })
    return templates.TemplateResponse(request=request, name="erp/erp_scrm.html", context={
        "request": request, "page_title": "영업/고객관리 대시보드",
        "user_name": u["user_name"],
        "recent_quotes": recent_quotes, "active_sos": active_sos,
        "alerts": alerts_rows,
        "qt_total_count": qt_total,
        "so_active_count": so_active,
        "so_shipped_count": so_shipped,
    })


@router.get("/erp_purch", response_class=HTMLResponse)
async def erp_purch(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    today = today_kst().isoformat()
    po_total = conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]
    po_inprogress = conn.execute(
        "SELECT COUNT(*) FROM purchase_orders WHERE status IN ('confirmed','partial')"
    ).fetchone()[0]
    delayed = conn.execute(
        "SELECT COUNT(*) FROM purchase_orders WHERE status IN ('confirmed','partial') AND delivery_date < ? AND delivery_date != ''",
        (today,)
    ).fetchone()[0]
    recent_pos = [dict(r) for r in conn.execute(
        """SELECT po.*, p.name as partner_name FROM purchase_orders po
           LEFT JOIN partners p ON po.partner_id=p.id
           ORDER BY po.id DESC LIMIT 10"""
    ).fetchall()]
    for r in recent_pos:
        r["status_label"] = PO_STATUS.get(r["status"], r["status"])
        r["status_class"] = PO_STATUS_CLASS.get(r["status"], "")

    alerts_rows = []
    overdue = conn.execute(
        """SELECT po.id, po.po_number, p.name as partner_name, po.delivery_date, po.status
           FROM purchase_orders po
           LEFT JOIN partners p ON po.partner_id=p.id
           WHERE po.status IN ('confirmed','partial') AND po.delivery_date < ? AND po.delivery_date != ''
           ORDER BY po.delivery_date LIMIT 3""", (today,)
    ).fetchall()
    for row in overdue:
        r = dict(row)
        alerts_rows.append({
            "id": r["id"], "title": f"{r['po_number']} {r['partner_name'] or ''} 납기 지연",
            "status": "urgent", "status_class": "status-badge status-reject",
            "status_label": "납기 지연", "created_at": r["delivery_date"],
        })
    return templates.TemplateResponse(request=request, name="erp/erp_purch.html", context={
        "request": request, "page_title": "구매관리 대시보드",
        "user_name": u["user_name"],
        "recent_pos": recent_pos, "alerts": alerts_rows,
        "po_total_count": po_total,
        "po_inprogress_count": po_inprogress,
        "delayed_count": delayed,
    })


@router.get("/erp_inventory", response_class=HTMLResponse)
async def erp_inventory(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    item_count = conn.execute("SELECT COUNT(*) FROM items WHERE is_active=1").fetchone()[0]
    warehouse_count = conn.execute("SELECT COUNT(*) FROM warehouses WHERE is_active=1").fetchone()[0]
    low_stock_count = conn.execute(
        "SELECT COUNT(*) FROM stock s JOIN items i ON s.item_id=i.id WHERE s.quantity <= i.safety_stock AND i.is_active=1"
    ).fetchone()[0]

    low_stocks = [dict(r) for r in conn.execute(
        """SELECT s.quantity, i.item_code, i.item_name, i.unit, i.safety_stock, w.name as wh_name
           FROM stock s
           JOIN items i ON s.item_id=i.id
           JOIN warehouses w ON s.warehouse_id=w.id
           WHERE s.quantity <= i.safety_stock AND i.is_active=1
           ORDER BY (s.quantity - i.safety_stock) ASC LIMIT 10"""
    ).fetchall()]

    recent_txns = [dict(r) for r in conn.execute(
        """SELECT st.*, i.item_name, w.name as wh_name
           FROM stock_transactions st
           JOIN items i ON st.item_id=i.id
           JOIN warehouses w ON st.warehouse_id=w.id
           ORDER BY st.id DESC LIMIT 10"""
    ).fetchall()]

    return templates.TemplateResponse(request=request, name="erp/erp_inventory.html", context={
        "request": request, "page_title": "재고관리 대시보드",
        "user_name": u["user_name"],
        "low_stocks": low_stocks, "recent_txns": recent_txns,
        "item_count": item_count, "warehouse_count": warehouse_count,
        "low_stock_count": low_stock_count,
    })


@router.get("/erp_product", response_class=HTMLResponse)
async def erp_product(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    wo_total = conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0]
    wo_active = conn.execute(
        "SELECT COUNT(*) FROM work_orders WHERE status IN ('released','in_progress')"
    ).fetchone()[0]
    wo_completed = conn.execute(
        "SELECT COUNT(*) FROM work_orders WHERE status='completed'"
    ).fetchone()[0]

    today = today_kst().isoformat()
    overdue = conn.execute(
        "SELECT COUNT(*) FROM work_orders WHERE planned_end < ? AND status IN ('planned','released','in_progress')",
        (today,),
    ).fetchone()[0]

    recent_wos = [dict(r) for r in conn.execute(
        """SELECT wo.*, i.item_name FROM work_orders wo
           LEFT JOIN items i ON wo.product_id=i.id
           ORDER BY wo.id DESC LIMIT 10"""
    ).fetchall()]
    for r in recent_wos:
        r["status_label"] = WO_STATUS.get(r["status"], r["status"])
        r["status_class"] = WO_STATUS_CLASS.get(r["status"], "")

    alerts_rows = []
    overdue_rows = conn.execute(
        """SELECT wo.id, wo.wo_number, i.item_name, wo.planned_end, wo.status
           FROM work_orders wo
           LEFT JOIN items i ON wo.product_id=i.id
           WHERE wo.status IN ('planned','released','in_progress') AND wo.planned_end < ? AND wo.planned_end != ''
           ORDER BY wo.planned_end LIMIT 3""", (today,)
    ).fetchall()
    for row in overdue_rows:
        r = dict(row)
        alerts_rows.append({
            "id": r["id"], "title": f"{r['wo_number']} {r['item_name'] or ''} 납기 지연",
            "status": "urgent", "status_class": "status-badge status-reject",
            "status_label": "납기 지연", "created_at": r["planned_end"],
        })

    return templates.TemplateResponse(request=request, name="erp/erp_product.html", context={
        "request": request, "page_title": "생산관리 대시보드",
        "user_name": u["user_name"],
        "work_order_count": wo_total,
        "production_inprogress_count": wo_active,
        "production_completed_count": wo_completed,
        "overdue_count": overdue,
        "recent_wos": recent_wos, "alerts": alerts_rows,
    })


@router.get("/erp_groupware", response_class=HTMLResponse)
async def erp_groupware(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
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
    notices = _stamp_date([dict(r) for r in conn.execute(
        "SELECT id, category, title, author, dept, created_at FROM posts "
        "WHERE category IN ('notice', 'general') ORDER BY id DESC LIMIT 5"
    ).fetchall()])
    alerts = _stamp_date(with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE status IN ('urgent','wait','pending') ORDER BY CASE status WHEN 'urgent' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 3"
    ).fetchall()))
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

# 전용 폼으로 대체된 구 라우트
for _legacy_name, _target_url in ERP_LEGACY_REDIRECTS.items():
    def _make_redirect(__url=_target_url):
        async def handler(request: Request, u: dict = Depends(require_login)):
            return RedirectResponse(__url, status_code=303)
        return handler
    router.add_api_route(f"/{_legacy_name}", _make_redirect(), methods=["GET"], response_class=HTMLResponse)


@router.get("/leave_approvals", response_class=HTMLResponse)
async def leave_approvals(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='hr_task' AND title LIKE '%휴가%' ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/leave_approvals.html", context={
        "request": request, "page_title": "휴가 승인",
        "user_name": u["user_name"], "docs": docs,
        "role": request.session.get("user_role", ""),
    })


@router.get("/recruitment_status", response_class=HTMLResponse)
async def recruitment_status(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="erp/recruitment_status.html", context={
        "request": request, "page_title": "채용 현황",
        "user_name": u["user_name"], "postings": [],
    })


@router.get("/outflow_list", response_class=HTMLResponse)
async def outflow_list(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='expense' AND status IN ('done','approved') ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "출금 완료 내역",
        "subtitle": "처리 완료된 지출 내역입니다.",
        "user_name": u["user_name"], "docs": docs,
    })


@router.get("/pending_payments", response_class=HTMLResponse)
async def pending_payments(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE doc_type='expense' AND status IN ('wait','pending','urgent') ORDER BY id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/fa_list.html", context={
        "request": request, "page_title": "미결제 내역",
        "subtitle": "처리 대기 중인 지출 요청입니다.",
        "user_name": u["user_name"], "docs": docs,
    })


@router.get("/production_status", response_class=HTMLResponse)
async def production_status(request: Request, all: int = 0, u: dict = Depends(require_login)):
    if all == 1:
        return RedirectResponse("/work-orders", status_code=303)
    return RedirectResponse("/work-orders?status=released", status_code=303)


@router.get("/equipment_alerts", response_class=HTMLResponse)
async def equipment_alerts(request: Request, u: dict = Depends(require_login)):
    return RedirectResponse("/work-orders", status_code=303)


@router.get("/po_status", response_class=HTMLResponse)
async def po_status(request: Request, u: dict = Depends(require_login)):
    return RedirectResponse("/purchase-orders", status_code=303)


@router.get("/delayed_delivery", response_class=HTMLResponse)
async def delayed_delivery(request: Request, u: dict = Depends(require_login)):
    return RedirectResponse("/purchase-orders?status=confirmed", status_code=303)


@router.get("/po_pending", response_class=HTMLResponse)
async def po_pending(request: Request, u: dict = Depends(require_login)):
    return RedirectResponse("/purchase-orders?status=confirmed", status_code=303)


@router.get("/outbound_status", response_class=HTMLResponse)
async def outbound_status(request: Request, u: dict = Depends(require_login)):
    return RedirectResponse("/stock", status_code=303)


@router.get("/low_stock_alerts", response_class=HTMLResponse)
async def low_stock_alerts(request: Request, u: dict = Depends(require_login)):
    return RedirectResponse("/stock?low=1", status_code=303)


@router.get("/sales_leads", response_class=HTMLResponse)
async def sales_leads(request: Request, u: dict = Depends(require_login)):
    return RedirectResponse("/quotations", status_code=303)


@router.get("/voc_list", response_class=HTMLResponse)
async def voc_list(request: Request, u: dict = Depends(require_login)):
    return RedirectResponse("/sales-orders", status_code=303)


@router.get("/approval_pending", response_class=HTMLResponse)
async def approval_pending(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    docs = with_status_meta(conn.execute(
        "SELECT * FROM erp_docs WHERE status IN ('wait','pending','urgent') ORDER BY CASE status WHEN 'urgent' THEN 0 ELSE 1 END, id DESC"
    ).fetchall())
    return templates.TemplateResponse(request=request, name="erp/approval_pending.html", context={
        "request": request, "page_title": "결재 대기",
        "user_name": u["user_name"], "docs": docs,
        "role": request.session.get("user_role", ""),
        "labels": ERP_DOC_TYPE_LABELS,
    })
