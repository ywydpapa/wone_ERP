import sqlite3
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.deps import get_db, require_login, templates
from core.erp_log import log_activity
from core.tz import now_kst, today_kst
from routers.erp_purchase import _next_po_number
from core.task_link import stamp_task

router = APIRouter()

PER_PAGE = 20

PR_STATUS = {
    "draft": "임시저장",
    "submitted": "제출",
    "approved": "승인",
    "rejected": "반려",
    "converted": "발주전환",
}

PR_STATUS_CLASS = {
    "draft": "status-badge status-wait",
    "submitted": "status-badge status-progress",
    "approved": "status-badge status-done",
    "rejected": "status-badge status-reject",
    "converted": "status-badge status-done",
}


def _next_pr_number(conn, seq_hint=None):
    year = today_kst().year
    if seq_hint is None:
        row = conn.execute(
            "SELECT pr_number FROM purchase_requisitions WHERE pr_number LIKE ? ORDER BY id DESC LIMIT 1",
            (f"PR-{year}-%",),
        ).fetchone()
        seq_hint = int(row["pr_number"].split("-")[-1]) + 1 if row else 1
    return f"PR-{year}-{seq_hint:04d}", seq_hint


@router.get("/purchase-requisitions", response_class=HTMLResponse)
async def pr_list(request: Request, status: str = "", page: int = 1,
                  u: dict = Depends(require_login), conn=Depends(get_db)):
    where = "WHERE 1=1"
    params = []
    if status:
        where += " AND pr.status=?"
        params.append(status)

    if u["role"] != "platform_staff":
        where += " AND pr.requester_id=?"
        params.append(u["id"])

    total = conn.execute(
        f"SELECT COUNT(*) FROM purchase_requisitions pr {where}", params
    ).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    rows = [dict(r) for r in conn.execute(f"""
        SELECT pr.*, u.name as requester_name
        FROM purchase_requisitions pr
        LEFT JOIN users u ON pr.requester_id=u.id
        {where}
        ORDER BY pr.id DESC
        LIMIT {PER_PAGE} OFFSET {(page-1)*PER_PAGE}
    """, params).fetchall()]

    for r in rows:
        r["status_label"] = PR_STATUS.get(r["status"], r["status"])
        r["status_class"] = PR_STATUS_CLASS.get(r["status"], "")
        line_sum = conn.execute(
            "SELECT COALESCE(SUM(quantity * estimated_price), 0) FROM pr_lines WHERE pr_id=?",
            (r["id"],),
        ).fetchone()[0]
        r["total_amount"] = line_sum

    return templates.TemplateResponse(request=request, name="erp/pr_list.html", context={
        "request": request, "page_title": "구매요청 목록",
        "user_name": u["name"],
        "rows": rows, "status": status,
        "pr_status": PR_STATUS,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/purchase-requisitions?status={status}",
    })


@router.get("/purchase-requisitions/new", response_class=HTMLResponse)
async def pr_form_new(request: Request,
                      u: dict = Depends(require_login), conn=Depends(get_db)):
    return templates.TemplateResponse(request=request, name="erp/pr_form.html", context={
        "request": request, "page_title": "구매요청 작성",
        "user_name": u["name"],
        "pr": None,
        "today": today_kst().isoformat(),
    })


@router.get("/purchase-requisitions/{pr_id}/edit", response_class=HTMLResponse)
async def pr_form_edit(request: Request, pr_id: int,
                       u: dict = Depends(require_login), conn=Depends(get_db)):
    pr = conn.execute(
        "SELECT * FROM purchase_requisitions WHERE id=? AND requester_id=?",
        (pr_id, u["id"]),
    ).fetchone()
    if not pr or pr["status"] != "draft":
        return RedirectResponse("/purchase-requisitions", status_code=303)
    pr = dict(pr)
    pr["lines"] = [dict(r) for r in conn.execute(
        """SELECT pl.*, i.item_code, i.unit
           FROM pr_lines pl LEFT JOIN items i ON pl.item_id=i.id
           WHERE pl.pr_id=? ORDER BY pl.line_no""", (pr_id,)
    ).fetchall()]
    return templates.TemplateResponse(request=request, name="erp/pr_form.html", context={
        "request": request, "page_title": "구매요청 수정",
        "user_name": u["name"],
        "pr": pr,
        "today": today_kst().isoformat(),
    })


@router.post("/purchase-requisitions/save")
async def pr_save(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    pr_id = int(form.get("pr_id", 0) or 0)
    request_date = form.get("request_date", today_kst().isoformat())
    need_date = form.get("need_date", "")
    notes = form.get("notes", "")

    line_nums = [n.strip() for n in form.get("line_nums", "").split(",") if n.strip()]
    lines = []
    for ln in line_nums:
        item_id = int(form.get(f"item_id_{ln}", 0) or 0)
        item_name = form.get(f"item_name_{ln}", "")
        qty = int(form.get(f"qty_{ln}", 0) or 0)
        est_price = int(form.get(f"price_{ln}", 0) or 0)
        line_notes = form.get(f"notes_{ln}", "")
        if item_name and qty > 0:
            lines.append((item_id or None, item_name, qty, est_price, line_notes))

    if not lines:
        return RedirectResponse("/purchase-requisitions/new", status_code=303)

    pr_id_existed = bool(pr_id)
    if pr_id:
        pr = conn.execute(
            "SELECT status, requester_id FROM purchase_requisitions WHERE id=?", (pr_id,)
        ).fetchone()
        if not pr or pr["status"] != "draft" or pr["requester_id"] != u["id"]:
            return RedirectResponse("/purchase-requisitions", status_code=303)
        conn.execute(
            "UPDATE purchase_requisitions SET request_date=?, need_date=?, notes=? WHERE id=?",
            (request_date, need_date, notes, pr_id),
        )
        conn.execute("DELETE FROM pr_lines WHERE pr_id=?", (pr_id,))
        pr_number = conn.execute(
            "SELECT pr_number FROM purchase_requisitions WHERE id=?", (pr_id,)
        ).fetchone()["pr_number"]
    else:
        pr_number, pr_seq = _next_pr_number(conn)
        task_id = stamp_task(conn, request, u["id"], "pr")
        while True:
            try:
                cur = conn.execute(
                    """INSERT INTO purchase_requisitions (pr_number, requester_id, dept, request_date, need_date, notes, task_id)
                       VALUES (?,?,?,?,?,?,?)""",
                    (pr_number, u["id"], "", request_date, need_date, notes, task_id),
                )
                break
            except sqlite3.IntegrityError:
                pr_seq += 1
                pr_number, _ = _next_pr_number(conn, pr_seq)
        pr_id = cur.lastrowid

    for i, (item_id, item_name, qty, est_price, ln_notes) in enumerate(lines, 1):
        conn.execute(
            "INSERT INTO pr_lines (pr_id, line_no, item_id, item_name, quantity, estimated_price, notes) VALUES (?,?,?,?,?,?,?)",
            (pr_id, i, item_id, item_name, qty, est_price, ln_notes),
        )

    if pr_id_existed:
        log_activity(conn, u["id"], "update", "pr", pr_id, pr_number, f"구매요청 수정 {pr_number}")
    else:
        log_activity(conn, u["id"], "create", "pr", pr_id, pr_number, f"구매요청 작성 {pr_number}")
    conn.commit()
    return RedirectResponse(f"/purchase-requisitions/{pr_id}", status_code=303)


@router.get("/purchase-requisitions/{pr_id}", response_class=HTMLResponse)
async def pr_detail(request: Request, pr_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    pr = conn.execute(
        """SELECT pr.*, u.name as requester_name
           FROM purchase_requisitions pr
           LEFT JOIN users u ON pr.requester_id=u.id
           WHERE pr.id=?""", (pr_id,)
    ).fetchone()
    if not pr:
        return RedirectResponse("/purchase-requisitions", status_code=303)
    pr = dict(pr)
    pr["status_label"] = PR_STATUS.get(pr["status"], pr["status"])
    pr["status_class"] = PR_STATUS_CLASS.get(pr["status"], "")

    lines = [dict(r) for r in conn.execute(
        """SELECT pl.*, i.item_code, i.unit
           FROM pr_lines pl LEFT JOIN items i ON pl.item_id=i.id
           WHERE pl.pr_id=? ORDER BY pl.line_no""", (pr_id,)
    ).fetchall()]

    total = 0
    for l in lines:
        l["amount"] = l["quantity"] * l["estimated_price"]
        total += l["amount"]

    approval = conn.execute(
        "SELECT a.*, u.name as approver_name FROM approvals a LEFT JOIN users u ON a.approver_id=u.id WHERE a.doc_type='pr' AND a.doc_id=? ORDER BY a.id DESC LIMIT 1",
        (pr_id,),
    ).fetchone()

    approval_status_labels = {"pending": "결재대기", "approved": "승인", "rejected": "반려"}
    approval_dict = None
    if approval:
        approval_dict = dict(approval)
        approval_dict["status_label"] = approval_status_labels.get(approval_dict["status"], approval_dict["status"])

    return templates.TemplateResponse(request=request, name="erp/pr_detail.html", context={
        "request": request, "page_title": f"구매요청 {pr['pr_number']}",
        "user_name": u["name"], "user_role": u["role"],
        "pr": pr, "lines": lines, "total": total,
        "approval": approval_dict,
    })


@router.post("/purchase-requisitions/{pr_id}/submit")
async def pr_submit(request: Request, pr_id: int,
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    pr = conn.execute(
        "SELECT status, requester_id, pr_number FROM purchase_requisitions WHERE id=?", (pr_id,)
    ).fetchone()
    if not pr or pr["status"] != "draft" or pr["requester_id"] != u["id"]:
        return RedirectResponse("/purchase-requisitions", status_code=303)
    conn.execute(
        "UPDATE purchase_requisitions SET status='submitted' WHERE id=?", (pr_id,)
    )
    conn.execute(
        "INSERT INTO approvals (doc_type, doc_id, step, approver_id) VALUES ('pr', ?, 1, NULL)",
        (pr_id,),
    )
    log_activity(conn, u["id"], "submit", "pr", pr_id, pr["pr_number"], f"구매요청 제출 {pr['pr_number']}")
    conn.commit()
    return RedirectResponse(f"/purchase-requisitions/{pr_id}", status_code=303)


@router.post("/purchase-requisitions/{pr_id}/approve")
async def pr_approve(request: Request, pr_id: int,
                     u: dict = Depends(require_login), conn=Depends(get_db)):
    pr = conn.execute("SELECT status, pr_number FROM purchase_requisitions WHERE id=?", (pr_id,)).fetchone()
    if not pr or pr["status"] != "submitted":
        return RedirectResponse("/purchase-requisitions", status_code=303)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE purchase_requisitions SET status='approved' WHERE id=?", (pr_id,))
    conn.execute(
        """UPDATE approvals SET status='approved', approver_id=?, acted_at=?
           WHERE doc_type='pr' AND doc_id=? AND status='pending'""",
        (u["id"], now, pr_id),
    )
    log_activity(conn, u["id"], "approve", "pr", pr_id, pr["pr_number"], f"구매요청 승인 {pr['pr_number']}")
    conn.commit()
    return RedirectResponse(f"/purchase-requisitions/{pr_id}", status_code=303)


@router.post("/purchase-requisitions/{pr_id}/reject")
async def pr_reject(request: Request, pr_id: int,
                    comment: str = Form(""),
                    u: dict = Depends(require_login), conn=Depends(get_db)):
    pr = conn.execute("SELECT status, pr_number FROM purchase_requisitions WHERE id=?", (pr_id,)).fetchone()
    if not pr or pr["status"] != "submitted":
        return RedirectResponse("/purchase-requisitions", status_code=303)
    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE purchase_requisitions SET status='rejected' WHERE id=?", (pr_id,))
    conn.execute(
        """UPDATE approvals SET status='rejected', approver_id=?, comment=?, acted_at=?
           WHERE doc_type='pr' AND doc_id=? AND status='pending'""",
        (u["id"], comment, now, pr_id),
    )
    log_activity(conn, u["id"], "reject", "pr", pr_id, pr["pr_number"], f"구매요청 반려 {pr['pr_number']}")
    conn.commit()
    return RedirectResponse(f"/purchase-requisitions/{pr_id}", status_code=303)


@router.post("/purchase-requisitions/{pr_id}/convert")
async def pr_convert_to_po(request: Request, pr_id: int,
                           u: dict = Depends(require_login), conn=Depends(get_db)):
    pr = conn.execute("SELECT * FROM purchase_requisitions WHERE id=?", (pr_id,)).fetchone()
    if not pr or pr["status"] != "approved":
        return RedirectResponse("/purchase-requisitions", status_code=303)

    pr_lines = conn.execute(
        "SELECT * FROM pr_lines WHERE pr_id=? ORDER BY line_no", (pr_id,)
    ).fetchall()

    po_number, po_seq = _next_po_number(conn)

    total = sum(ln["quantity"] * ln["estimated_price"] for ln in pr_lines)
    tax = int(total * 0.1)

    while True:
        try:
            cur = conn.execute(
                """INSERT INTO purchase_orders (po_number, po_date, total_amount, tax_amount, notes, created_by)
                   VALUES (?, date('now','localtime'), ?, ?, ?, ?)""",
                (po_number, total, tax, f"구매요청 {pr['pr_number']}에서 전환", u["id"]),
            )
            break
        except sqlite3.IntegrityError:
            po_seq += 1
            po_number, _ = _next_po_number(conn, po_seq)
    po_id = cur.lastrowid

    for ln in pr_lines:
        conn.execute(
            "INSERT INTO po_lines (po_id, line_no, item_id, quantity, unit_price, amount) VALUES (?,?,?,?,?,?)",
            (po_id, ln["line_no"], ln["item_id"], ln["quantity"], ln["estimated_price"],
             ln["quantity"] * ln["estimated_price"]),
        )

    conn.execute("UPDATE purchase_requisitions SET status='converted' WHERE id=?", (pr_id,))
    log_activity(conn, u["id"], "convert", "pr", pr_id, pr["pr_number"], f"구매요청 발주전환 {pr['pr_number']} -> {po_number}")
    conn.commit()
    return RedirectResponse(f"/purchase-orders/{po_id}", status_code=303)
