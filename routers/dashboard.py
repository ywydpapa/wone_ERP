import json
from datetime import datetime, timedelta

from core.tz import today_kst, now_kst

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core.books import book_of
from core.deps import get_db, require_login, templates, get_employee_id
from core.task_link import erp_scope
from routers.platform import TASK_TYPE_LABELS, STATUS_LABELS, REQUEST_STATUS_LABELS

router = APIRouter()

DASH_WIDGETS = {
    "platform_staff": {"stats": "현황 통계", "requests": "최근 업무 요청", "overdue": "마감 초과", "today_att": "금일 출퇴근"},
    "worker": {"att": "출퇴근", "tasks": "내 업무", "stats": "통계", "quick": "바로가기"},
    "client": {"stats": "현황 통계", "today_att": "금일 출퇴근", "requests": "최근 업무 요청", "req_summary": "업무 요청 현황"},
}

DASH_MENUS = {
    "platform_staff": {
        "m_workers":      ("근로자 관리",    "/hr/employees",                   "SELECT COUNT(*) FROM employees WHERE status='active'", None),
        "m_companies":    ("고객사",          "/platform/companies",             "SELECT COUNT(*) FROM client_companies WHERE status='active'", None),
        "m_work_dash":    ("업무 현황",       "/platform/work-requests/dashboard", None, None),
        "m_assign":       ("업무 배정",       "/platform/work-requests",         "SELECT COUNT(*) FROM work_requests WHERE status='submitted'", None),
        "m_diary_review": ("업무일지 검토",   "/daily-report/review-list",       "SELECT COUNT(*) FROM jobs WHERE review_status='pending' AND status!='trash'", None),
        "m_help":         ("도움 요청",       "/platform/help-requests",         "SELECT COUNT(*) FROM help_requests WHERE status='open'", None),
        "m_att":          ("근태 관리",       "/hr/attendance",                  "SELECT COUNT(*) FROM attendance WHERE work_date=date('now','localtime') AND clock_in IS NOT NULL", None),
        "m_att_daily":    ("일일 입력",       "/hr/attendance/daily",            None, None),
        "m_att_sheet":    ("출근부",          "/hr/attendance/sheet",            None, None),
        "m_appeals":      ("소명 관리",       "/hr/attendance/appeals",          "SELECT COUNT(*) FROM attendance WHERE appeal='pending'", None),
        "m_payroll":      ("급여대장",        "/payroll/ledger",                 None, None),
        "m_ins_rates":    ("보험요율 관리",   "/hr/insurance-rates",             None, None),
        "m_roster":       ("근로자 명부",     "/roster",                        None, None),
        "m_monthly":      ("월간 리포트",     "/platform/monthly-report",        "SELECT COUNT(*) FROM monthly_reports WHERE status='draft'", None),
        "m_export_tpl":   ("반출 템플릿",     "/platform/export-templates",      None, None),
        "m_export_logs":  ("반출 이력",       "/platform/export-logs",           None, None),
    },
    "worker": {
        "m_my_tasks": ("내 업무",    "/my-tasks",           "SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status IN ('assigned','in_progress')", "emp"),
        "m_diary":    ("업무일지",   "/job_diary",          "SELECT COUNT(*) FROM jobs WHERE user_id=? AND work_date=date('now','localtime') AND status!='trash'", "user"),
        "m_daily":    ("일일 보고",  "/daily-report",       None, None),
        "m_summary":  ("업무 요약",  "/daily-report/summary", None, None),
        "m_progress": ("진행 업무",  "/progress_jobs",      "SELECT COUNT(*) FROM jobs WHERE user_id=? AND status NOT IN ('done','trash')", "user"),
        "m_done":     ("완료 업무",  "/completed_jobs",     None, None),
        "m_calendar": ("일정 관리",  "/calendar",           None, None),
        "m_msg":      ("메시지함",   "/newarrived_jobs",    "SELECT COUNT(*) FROM messages WHERE user_id=? AND direction='in' AND is_read=0", "user"),
        "m_my_att":   ("근태 확인",  "/mypage/attendance",  "SELECT COUNT(*) FROM attendance WHERE employee_id=? AND work_date>=date('now','start of month','localtime')", "emp"),
        "m_payslip":  ("급여 조회",  "/mypage/payslip",     None, None),
        "m_mypage":   ("마이페이지", "/mypage",             None, None),
    },
    "client": {
        "m_workers":  ("근로자 관리", "/client/workers",          "SELECT COUNT(*) FROM employees WHERE company_id=? AND status='active'", "company"),
        "m_accom":    ("편의지원",    "/client/accommodation",    "SELECT COUNT(*) FROM accommodation_requests ar JOIN employees e ON ar.employee_id=e.id WHERE e.company_id=? AND ar.status='pending'", "company"),
        "m_requests": ("업무 요청",   "/client/requests",         "SELECT COUNT(*) FROM work_requests WHERE company_id=? AND status IN ('submitted','review','accepted','in_progress')", "company"),
        "m_att":      ("근태 확인",   "/client/attendance",       "SELECT COUNT(*) FROM attendance a JOIN employees e ON a.employee_id=e.id WHERE e.company_id=? AND a.work_date=date('now','localtime')", "company"),
        "m_att_sheet":("출근부",      "/client/attendance/sheet", None, None),
        "m_appeals":  ("소명 관리",   "/client/attendance/appeals", "SELECT COUNT(*) FROM attendance a JOIN employees e ON a.employee_id=e.id WHERE e.company_id=? AND a.appeal='pending'", "company"),
        "m_payroll":  ("급여 관리",   "/payroll",          "SELECT COUNT(*) FROM employees WHERE company_id=? AND status='active' AND id NOT IN (SELECT employee_id FROM payslips WHERE pay_year=CAST(strftime('%Y',date('now','localtime')) AS INTEGER) AND pay_month=CAST(strftime('%m',date('now','localtime')) AS INTEGER) AND status='confirmed')", "company"),
        "m_leave":    ("휴가 관리",   "/client/leave",            "SELECT COUNT(*) FROM leave_requests lr JOIN employees e ON lr.employee_id=e.id WHERE e.company_id=? AND lr.status='pending'", "company"),
        "m_certs":    ("증명서 현황", "/client/certificates",     "SELECT COUNT(*) FROM certificate_requests cr JOIN employees e ON cr.employee_id=e.id WHERE e.company_id=? AND cr.status='pending'", "company"),
        "m_monthly":  ("월간 리포트", "/client/monthly-report",   None, None),
        "m_contract": ("계약 관리",   "/client/contract",         None, None),
    },
}

_COL_CLS = {4: "col-6 col-lg-3", 6: "col-6 col-lg-2", 8: "col-3 dash-col-8"}


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    role = user["role"]
    widget_defs = DASH_WIDGETS.get(role) or DASH_WIDGETS["client"]
    menu_defs = DASH_MENUS.get(role, {})

    row = conn.execute(
        "SELECT widgets, cols FROM dashboard_prefs WHERE user_id=?", (user["id"],)
    ).fetchone()
    if row:
        widgets = set(json.loads(row["widgets"])) & (set(widget_defs) | set(menu_defs))
        cols = row["cols"] or 4
    else:
        widgets = set(widget_defs)
        cols = 4
    col_cls = _COL_CLS.get(cols, "col-6 col-lg-3")

    def build_menu_cards(scope_vals):
        cards = []
        for key, (label, url, sql, scope) in menu_defs.items():
            if key not in widgets:
                continue
            cnt = None
            if sql:
                if scope and scope_vals.get(scope) is None:
                    cnt = 0
                else:
                    args = (scope_vals[scope],) if scope else ()
                    cnt = conn.execute(sql, args).fetchone()[0]
            cards.append({"key": key, "label": label, "url": url, "cnt": cnt})
        return cards

    if role == "platform_staff":
        today = today_kst()
        today_str = today.isoformat()
        week_ago = (today - timedelta(days=7)).isoformat()

        new_requests = conn.execute(
            "SELECT COUNT(*) FROM work_requests WHERE status='submitted'"
        ).fetchone()[0]
        in_progress = conn.execute(
            "SELECT COUNT(*) FROM work_requests WHERE status='in_progress'"
        ).fetchone()[0]
        review_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='review'"
        ).fetchone()[0]
        week_completed = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='completed' AND completed_at>=?",
            (week_ago,)
        ).fetchone()[0]

        recent_requests = conn.execute(
            "SELECT wr.*, cc.name AS company_name "
            "FROM work_requests wr "
            "LEFT JOIN client_companies cc ON wr.company_id=cc.id "
            "ORDER BY wr.created_at DESC LIMIT 5"
        ).fetchall()

        overdue_requests = conn.execute(
            "SELECT wr.id, wr.title, wr.due_date, wr.status, cc.name AS company_name "
            "FROM work_requests wr "
            "LEFT JOIN client_companies cc ON wr.company_id=cc.id "
            "WHERE wr.due_date < ? AND wr.status NOT IN ('completed','closed','cancelled') "
            "ORDER BY wr.due_date",
            (today_str,)
        ).fetchall()

        today_att = conn.execute(
            "SELECT e.name, cc.name AS company_name, a.clock_in, a.clock_out, a.status "
            "FROM attendance a "
            "JOIN employees e ON a.employee_id=e.id "
            "LEFT JOIN client_companies cc ON e.company_id=cc.id "
            "WHERE a.work_date=? ORDER BY a.clock_in DESC",
            (today_str,),
        ).fetchall()
        att_total = conn.execute(
            "SELECT COUNT(*) FROM employees WHERE status='active'"
        ).fetchone()[0]

        return templates.TemplateResponse(
            request=request, name="platform/dashboard.html", context={
                "request": request,
                "page_title": "운영 현황",
                "user_name": user["name"],
                "new_requests": new_requests,
                "in_progress": in_progress,
                "review_tasks": review_tasks,
                "week_completed": week_completed,
                "recent_requests": recent_requests,
                "overdue_requests": overdue_requests,
                "today_att": today_att,
                "att_total": att_total,
                "att_clocked": len(today_att),
                "request_status_labels": REQUEST_STATUS_LABELS,
                "status_labels": STATUS_LABELS,
                "widgets": widgets,
                "widget_defs": widget_defs,
                "menu_cards": build_menu_cards({}),
                "menu_defs": menu_defs,
                "cols": cols,
                "col_cls": col_cls,
            }
        )

    elif role == "worker":
        today = today_kst().isoformat()
        now = now_kst()
        employee_id = get_employee_id(conn, user["id"])

        my_tasks = 0
        completed_today = 0
        today_attendance = None
        tasks_list = []
        unread_notif = 0

        if employee_id:
            my_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status IN ('assigned','in_progress')",
                (employee_id,)
            ).fetchone()[0]
            completed_today = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status='completed' AND completed_at LIKE ?",
                (employee_id, today + "%")
            ).fetchone()[0]
            att_row = conn.execute(
                "SELECT * FROM attendance WHERE employee_id=? AND work_date=?",
                (employee_id, today)
            ).fetchone()
            if att_row:
                today_attendance = dict(att_row)
                ci = today_attendance.get('clock_in') or ''
                today_attendance['ci_short'] = ci[:5] if ci else '-'
                co = today_attendance.get('clock_out') or ''
                today_attendance['co_short'] = co[:5] if co else ''
                if ci and not co:
                    ci_dt = datetime.strptime(f"{today} {ci}", "%Y-%m-%d %H:%M:%S")
                    diff = now.replace(tzinfo=None) - ci_dt
                    today_attendance['elapsed_h'] = int(diff.total_seconds() // 3600)
                    today_attendance['elapsed_m'] = int((diff.total_seconds() % 3600) // 60)
            tasks_list = conn.execute(
                "SELECT * FROM tasks WHERE assigned_to=? AND status NOT IN ('completed','cancelled') "
                "ORDER BY priority DESC, due_date LIMIT 10",
                (employee_id,)
            ).fetchall()
            unread_notif = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                (user["id"],)
            ).fetchone()[0]

        weekdays = ['월', '화', '수', '목', '금', '토', '일']
        today_label = f"{now.month}월 {now.day}일 {weekdays[now.weekday()]}요일"

        return templates.TemplateResponse(
            request=request, name="worker/dashboard.html", context={
                "request": request,
                "page_title": "홈",
                "user_name": user["name"],
                "my_tasks": my_tasks,
                "completed_today": completed_today,
                "today_attendance": today_attendance,
                "tasks_list": tasks_list,
                "task_type_labels": TASK_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
                "today_label": today_label,
                "unread_notif": unread_notif,
                "widgets": widgets,
                "widget_defs": widget_defs,
                "menu_cards": build_menu_cards({"emp": employee_id, "user": user["id"]}),
                "menu_defs": menu_defs,
                "cols": cols,
                "col_cls": col_cls,
            }
        )

    else:
        today = today_kst().isoformat()
        client_user = conn.execute(
            "SELECT company_id FROM client_users WHERE user_id = ?", (user["id"],)
        ).fetchone()
        company_id = client_user["company_id"] if client_user else None

        total_requests = 0
        active_requests = 0
        completed_tasks = 0
        recent_requests = []
        worker_count = 0
        today_attendance = 0
        pending_leave = 0
        pending_accom = 0
        total_worker_count = 0
        inactive_count = 0
        new_hire_count = 0
        today_att = []

        if company_id:
            total_requests = conn.execute(
                "SELECT COUNT(*) FROM work_requests WHERE company_id=?",
                (company_id,)
            ).fetchone()[0]
            active_requests = conn.execute(
                "SELECT COUNT(*) FROM work_requests WHERE company_id=? AND status IN ('submitted','review','accepted','in_progress')",
                (company_id,)
            ).fetchone()[0]
            completed_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks t "
                "JOIN work_requests w ON t.work_request_id = w.id "
                "WHERE w.company_id=? AND t.status='completed'",
                (company_id,)
            ).fetchone()[0]
            recent_requests = conn.execute(
                "SELECT * FROM work_requests WHERE company_id=? ORDER BY created_at DESC LIMIT 5",
                (company_id,)
            ).fetchall()
            worker_count = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE company_id=? AND status='active'",
                (company_id,)
            ).fetchone()[0]
            today_attendance = conn.execute(
                "SELECT COUNT(*) FROM attendance a "
                "JOIN employees e ON a.employee_id=e.id "
                "WHERE e.company_id=? AND a.work_date=?",
                (company_id, today)
            ).fetchone()[0]
            pending_leave = conn.execute(
                "SELECT COUNT(*) FROM leave_requests lr "
                "JOIN employees e ON lr.employee_id=e.id "
                "WHERE e.company_id=? AND lr.status='pending'",
                (company_id,)
            ).fetchone()[0]
            pending_accom = conn.execute(
                "SELECT COUNT(*) FROM accommodation_requests ar "
                "JOIN employees e ON ar.employee_id=e.id "
                "WHERE e.company_id=? AND ar.status='pending'",
                (company_id,)
            ).fetchone()[0]
            total_worker_count = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE company_id=?",
                (company_id,)
            ).fetchone()[0]
            inactive_count = total_worker_count - worker_count
            month_start = today_kst().replace(day=1).isoformat()
            new_hire_count = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE company_id=? AND hire_date>=?",
                (company_id, month_start)
            ).fetchone()[0]
            today_att = conn.execute(
                "SELECT e.name, a.clock_in, a.clock_out, a.status "
                "FROM attendance a "
                "JOIN employees e ON a.employee_id=e.id "
                "WHERE e.company_id=? AND a.work_date=? ORDER BY a.clock_in DESC",
                (company_id, today),
            ).fetchall()

        return templates.TemplateResponse(
            request=request, name="client/dashboard.html", context={
                "request": request,
                "page_title": "고객사 현황",
                "user_name": user["name"],
                "total_requests": total_requests,
                "active_requests": active_requests,
                "completed_tasks": completed_tasks,
                "recent_requests": [dict(r) | {"created_date": r["created_at"][:10] if r["created_at"] else "-"} for r in recent_requests],
                "worker_count": total_worker_count,
                "today_attendance": today_attendance,
                "today_att": today_att,
                "pending_leave": pending_leave,
                "pending_accom": pending_accom,
                "active_worker_count": worker_count,
                "inactive_count": inactive_count,
                "new_hire_count": new_hire_count,
                "task_type_labels": TASK_TYPE_LABELS,
                "request_status_labels": REQUEST_STATUS_LABELS,
                "widgets": widgets,
                "widget_defs": widget_defs,
                "menu_cards": build_menu_cards({"company": company_id}),
                "menu_defs": menu_defs,
                "cols": cols,
                "col_cls": col_cls,
            }
        )


@router.post("/dashboard/widgets")
async def save_widgets(request: Request, user: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    defs = DASH_WIDGETS.get(user["role"]) or DASH_WIDGETS["client"]
    menu_defs = DASH_MENUS.get(user["role"], {})
    picked = [k for k in list(defs) + list(menu_defs) if k in form]
    try:
        cols = int(form.get("cols", "4"))
    except ValueError:
        cols = 4
    if cols not in (4, 6, 8):
        cols = 4
    conn.execute(
        "INSERT INTO dashboard_prefs (user_id, widgets, cols, updated_at) VALUES (?, ?, ?, datetime('now','localtime')) "
        "ON CONFLICT(user_id) DO UPDATE SET widgets=excluded.widgets, cols=excluded.cols, updated_at=excluded.updated_at",
        (user["id"], json.dumps(picked), cols),
    )
    conn.commit()
    return RedirectResponse("/", status_code=303)


@router.get("/api/search")
async def global_search(
    request: Request,
    q: str = Query("", min_length=1),
    user: dict = Depends(require_login),
    conn=Depends(get_db),
):
    role = user["role"]
    q = q.strip()
    if not q:
        return JSONResponse([])

    like = f"%{q}%"
    results = []

    if role == "platform_staff":
        for r in conn.execute(
            "SELECT id, name, employee_no FROM employees WHERE name LIKE ? OR employee_no LIKE ? LIMIT 5",
            (like, like),
        ).fetchall():
            results.append({"type": "employee", "label": f"{r['name']} ({r['employee_no']})", "url": f"/hr/employees/{r['id']}"})

        for r in conn.execute(
            "SELECT id, title FROM work_requests WHERE title LIKE ? OR id=? LIMIT 5",
            (like, q if q.isdigit() else -1),
        ).fetchall():
            results.append({"type": "work_request", "label": f"[업무요청] {r['title']}", "url": f"/platform/work-requests/{r['id']}"})

    elif role == "client":
        cu = conn.execute("SELECT company_id FROM client_users WHERE user_id=?", (user["id"],)).fetchone()
        cid = cu["company_id"] if cu else None
        if cid:
            for r in conn.execute(
                "SELECT id, name, employee_no FROM employees WHERE company_id=? AND (name LIKE ? OR employee_no LIKE ?) LIMIT 5",
                (cid, like, like),
            ).fetchall():
                results.append({"type": "employee", "label": f"{r['name']} ({r['employee_no']})", "url": f"/client/attendance/{r['id']}"})
            for r in conn.execute(
                "SELECT id, title FROM work_requests WHERE company_id=? AND title LIKE ? LIMIT 5",
                (cid, like),
            ).fetchall():
                results.append({"type": "work_request", "label": f"[업무요청] {r['title']}", "url": f"/client/requests/{r['id']}"})

    elif role == "worker":
        for r in conn.execute(
            "SELECT id, title, work_date FROM jobs WHERE user_id=? AND (title LIKE ? OR details LIKE ?) AND status != 'trash' ORDER BY id DESC LIMIT 5",
            (user["id"], like, like),
        ).fetchall():
            results.append({"type": "job", "label": f"[업무] {r['title']}", "url": f"/job/{r['id']}"})

    if role != "client":
        book = book_of(conn, user)
        doc_scope_sql, doc_scope_args = erp_scope(conn, user, "d")
        if book is not None:
            for r in conn.execute(
                f"""SELECT id, doc_number, title FROM erp_docs d
                    WHERE slip_date IS NOT NULL AND (doc_number LIKE ? OR title LIKE ?)
                      AND (d.doc_type!='expense' OR d.company_id=?) AND {doc_scope_sql} LIMIT 5""",
                (like, like, book, *doc_scope_args),
            ).fetchall():
                label = r["title"][:30] if r["title"] else ""
                results.append({"type": "slip", "label": f"[전표] {r['doc_number']} {label}", "url": f"/erp_doc/{r['id']}"})

        if book is not None:
            for r in conn.execute(
                "SELECT id, item_code, item_name FROM items WHERE company_id=? AND (item_code LIKE ? OR item_name LIKE ?) LIMIT 5",
                (book, like, like),
            ).fetchall():
                results.append({"type": "item", "label": f"[품목] {r['item_code']} {r['item_name']}", "url": f"/items/{r['id']}/edit"})

        if book is not None:
            for r in conn.execute(
                "SELECT id, name, biz_no FROM partners WHERE company_id=? AND (name LIKE ? OR biz_no LIKE ?) LIMIT 5",
                (book, like, like),
            ).fetchall():
                results.append({"type": "partner", "label": f"[거래처] {r['name']}", "url": f"/partners/{r['id']}/edit"})

        po_scope_sql, po_scope_args = erp_scope(conn, user, "po")
        for r in conn.execute(
            f"SELECT po.id, po.po_number FROM purchase_orders po WHERE po.po_number LIKE ? AND {po_scope_sql} LIMIT 3",
            (like, *po_scope_args),
        ).fetchall():
            results.append({"type": "po", "label": f"[발주] {r['po_number']}", "url": f"/purchase-orders/{r['id']}"})

        so_scope_sql, so_scope_args = erp_scope(conn, user, "so")
        for r in conn.execute(
            f"SELECT so.id, so.so_number FROM sales_orders so WHERE so.so_number LIKE ? AND {so_scope_sql} LIMIT 3",
            (like, *so_scope_args),
        ).fetchall():
            results.append({"type": "so", "label": f"[수주] {r['so_number']}", "url": f"/sales-orders/{r['id']}"})

    return JSONResponse(results[:15])


@router.get("/workspace", response_class=HTMLResponse)
async def workspace(request: Request, user: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="workspace.html", context={})


FAV_MAX = 20


def _favs(conn, uid):
    return [dict(r) for r in conn.execute(
        "SELECT href, label FROM menu_favs WHERE user_id=? ORDER BY sort, created_at", (uid,)
    ).fetchall()]


@router.get("/menu-favs")
async def menu_favs(user: dict = Depends(require_login), conn=Depends(get_db)):
    return _favs(conn, user["id"])


@router.post("/menu-favs")
async def menu_fav_add(href: str = Form(...), label: str = Form(...),
                       user: dict = Depends(require_login), conn=Depends(get_db)):
    href, label = href.strip(), label.strip()[:40]
    if not href.startswith("/") or href.startswith("//") or len(href) > 200 or not label:
        return JSONResponse({"error": "잘못된 메뉴입니다."}, status_code=400)
    cnt, last = conn.execute("SELECT COUNT(*), COALESCE(MAX(sort), 0) FROM menu_favs WHERE user_id=?", (user["id"],)).fetchone()
    if cnt >= FAV_MAX:
        return JSONResponse({"error": f"즐겨찾기는 {FAV_MAX}개까지 등록할 수 있습니다."}, status_code=400)
    conn.execute("INSERT OR IGNORE INTO menu_favs (user_id, href, label, sort) VALUES (?,?,?,?)",
                 (user["id"], href, label, last + 1))
    conn.commit()
    return _favs(conn, user["id"])


@router.delete("/menu-favs")
async def menu_fav_del(href: str = Form(...), user: dict = Depends(require_login), conn=Depends(get_db)):
    conn.execute("DELETE FROM menu_favs WHERE user_id=? AND href=?", (user["id"], href))
    conn.commit()
    return _favs(conn, user["id"])


@router.patch("/menu-favs")
async def menu_fav_sort(request: Request, user: dict = Depends(require_login), conn=Depends(get_db)):
    hrefs = (await request.form()).getlist("href")
    for i, href in enumerate(hrefs[:FAV_MAX]):
        conn.execute("UPDATE menu_favs SET sort=? WHERE user_id=? AND href=?", (i, user["id"], href))
    conn.commit()
    return _favs(conn, user["id"])


MENU_GROUPS = ("work", "fi", "hr", "mm", "sales")


@router.put("/menu-prefs")
async def menu_prefs_save(request: Request, user: dict = Depends(require_login), conn=Depends(get_db)):
    hidden = [g for g in MENU_GROUPS if g in (await request.form()).getlist("hidden")]
    conn.execute(
        "INSERT INTO menu_prefs (user_id, hidden) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET hidden=excluded.hidden",
        (user["id"], ",".join(hidden)))
    conn.commit()
    return {"hidden": hidden}

