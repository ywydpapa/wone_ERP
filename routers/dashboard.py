import json
from datetime import datetime

from core.tz import today_kst, now_kst

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core.approval import box_sql
from core.books import book_of
from core.deps import get_db, require_login, templates, get_employee_id
from core.task_link import erp_scope
from routers.platform import TASK_TYPE_LABELS, STATUS_LABELS, REQUEST_STATUS_LABELS

router = APIRouter()

DASH_WIDGETS = {
    "platform_staff": {"todo": "처리 대기", "notice": "공지사항", "today_att": "금일 출퇴근", "requests": "최근 업무 요청"},
    "worker": {"att": "출퇴근", "tasks": "내 업무", "stats": "업무 현황", "quick": "바로가기"},
    "client": {"todo": "처리 대기", "notice": "공지사항", "today_att": "금일 출퇴근", "requests": "최근 업무 요청"},
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

MENU_ICONS = {
    "m_workers": "fa-users", "m_companies": "fa-building", "m_work_dash": "fa-chart-column", "m_assign": "fa-share-from-square",
    "m_diary_review": "fa-file-circle-check", "m_help": "fa-life-ring", "m_att": "fa-user-clock", "m_att_daily": "fa-pen-to-square",
    "m_att_sheet": "fa-table-list", "m_appeals": "fa-comment-dots", "m_payroll": "fa-money-check-dollar", "m_ins_rates": "fa-percent",
    "m_roster": "fa-address-book", "m_monthly": "fa-file-lines", "m_export_tpl": "fa-file-export", "m_export_logs": "fa-clock-rotate-left",
    "m_my_tasks": "fa-list-check", "m_diary": "fa-book", "m_daily": "fa-file-pen", "m_summary": "fa-chart-pie",
    "m_progress": "fa-spinner", "m_done": "fa-circle-check", "m_calendar": "fa-calendar-days", "m_msg": "fa-envelope",
    "m_my_att": "fa-user-clock", "m_payslip": "fa-receipt", "m_mypage": "fa-id-card", "m_accom": "fa-hand-holding-heart",
    "m_requests": "fa-inbox", "m_leave": "fa-umbrella-beach", "m_certs": "fa-certificate", "m_contract": "fa-file-signature",
}
_ATT_LATE = {"late": "지각", "early_leave": "조퇴", "late_early": "지각/조퇴"}


def _notices(conn):
    rows = conn.execute(
        "SELECT id, title, created_at FROM posts WHERE category='notice' ORDER BY created_at DESC LIMIT 6"
    ).fetchall()
    return [{"id": r["id"], "title": r["title"], "day": (r["created_at"] or "")[5:10]} for r in rows]


def _att_rows(rows):
    return [{
        "name": r["name"],
        "ci": (r["clock_in"] or "")[:5] or "-",
        "co": (r["clock_out"] or "")[:5] or "-",
        "late": _ATT_LATE.get(r["status"]),
    } for r in rows[:8]]


def _day_label():
    now = now_kst()
    return f"{now.month}월 {now.day}일 {'월화수목금토일'[now.weekday()]}요일"


def _cnt(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def _wait_docs(conn, uid):
    sql, args = box_sql("wait", uid)
    return _cnt(conn, f"SELECT COUNT(*) FROM erp_docs WHERE {sql}", *args)


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
        "SELECT widgets FROM dashboard_prefs WHERE user_id=?", (user["id"],)
    ).fetchone()
    if row:
        widgets = set(json.loads(row["widgets"])) & (set(widget_defs) | set(menu_defs))
    else:
        widgets = set(widget_defs)

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
            cards.append({"key": key, "label": label, "url": url, "cnt": cnt, "icon": MENU_ICONS.get(key, "fa-arrow-up-right-from-square")})
        return cards

    if role == "platform_staff":
        today_str = today_kst().isoformat()

        overdue = _cnt(
            conn,
            "SELECT COUNT(*) FROM work_requests WHERE due_date < ? AND status NOT IN ('completed','closed','cancelled')",
            today_str,
        )
        todo = [
            ("업무 요청 접수", _cnt(conn, "SELECT COUNT(*) FROM work_requests WHERE status='submitted'"), "/platform/work-requests?status=submitted", False),
            ("작업 검토", _cnt(conn, "SELECT COUNT(*) FROM tasks WHERE status='review'"), "/platform/work-requests/dashboard", False),
            ("업무일지 검토", _cnt(conn, "SELECT COUNT(*) FROM jobs WHERE review_status='pending' AND status!='trash'"), "/daily-report/review-list", False),
            ("도움 요청", _cnt(conn, "SELECT COUNT(*) FROM help_requests WHERE status='open'"), "/platform/help-requests", False),
            ("결재 대기", _wait_docs(conn, user["id"]), "/approvals?box=wait", False),
            ("근태 소명", _cnt(conn, "SELECT COUNT(*) FROM attendance WHERE appeal='pending'"), "/hr/attendance/appeals", False),
            ("마감 초과 요청", overdue, "/platform/work-requests", True),
        ]

        recent_requests = conn.execute(
            "SELECT wr.*, cc.name AS company_name "
            "FROM work_requests wr "
            "LEFT JOIN client_companies cc ON wr.company_id=cc.id "
            "ORDER BY wr.created_at DESC LIMIT 5"
        ).fetchall()

        today_att = conn.execute(
            "SELECT e.name, a.clock_in, a.clock_out, a.status "
            "FROM attendance a "
            "JOIN employees e ON a.employee_id=e.id "
            "WHERE a.work_date=? ORDER BY a.clock_in DESC",
            (today_str,),
        ).fetchall()

        return templates.TemplateResponse(
            request=request, name="platform/dashboard.html", context={
                "request": request,
                "page_title": "운영 현황",
                "today_label": _day_label(),
                "user_name": user["name"],
                "todo": todo,
                "notices": _notices(conn),
                "recent_requests": recent_requests,
                "today_att": _att_rows(today_att),
                "att_total": _cnt(conn, "SELECT COUNT(*) FROM employees WHERE status='active'"),
                "att_clocked": len(today_att),
                "request_status_labels": REQUEST_STATUS_LABELS,
                "widgets": widgets,
                "widget_defs": widget_defs,
                "menu_cards": build_menu_cards({}),
                "menu_defs": menu_defs,
            }
        )

    elif role == "worker":
        today = today_kst().isoformat()
        now = now_kst()
        employee_id = get_employee_id(conn, user["id"])

        my_tasks = 0
        completed_today = 0
        att = {"state": "출근 전", "ci": "-", "co": "-", "elapsed": "", "action": "clock-in" if employee_id else ""}
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
                "SELECT clock_in, clock_out FROM attendance WHERE employee_id=? AND work_date=?",
                (employee_id, today)
            ).fetchone()
            ci = att_row["clock_in"] if att_row else None
            co = att_row["clock_out"] if att_row else None
            if ci and co:
                att.update(state="퇴근", ci=ci[:5], co=co[:5], action="")
            elif ci:
                diff = now.replace(tzinfo=None) - datetime.strptime(f"{today} {ci}", "%Y-%m-%d %H:%M:%S")
                mins = int(diff.total_seconds() // 60)
                att.update(state="근무중", ci=ci[:5], elapsed=f"{mins // 60}시간 {mins % 60}분", action="clock-out")
            tasks_list = conn.execute(
                "SELECT * FROM tasks WHERE assigned_to=? AND status NOT IN ('completed','cancelled') "
                "ORDER BY priority DESC, due_date LIMIT 10",
                (employee_id,)
            ).fetchall()
            unread_notif = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                (user["id"],)
            ).fetchone()[0]

        today_label = _day_label()

        return templates.TemplateResponse(
            request=request, name="worker/dashboard.html", context={
                "request": request,
                "page_title": "홈",
                "user_name": user["name"],
                "my_tasks": my_tasks,
                "completed_today": completed_today,
                "att": att,
                "tasks_list": tasks_list,
                "task_type_labels": TASK_TYPE_LABELS,
                "status_labels": STATUS_LABELS,
                "today_label": today_label,
                "unread_notif": unread_notif,
                "widgets": widgets,
                "widget_defs": widget_defs,
                "menu_cards": build_menu_cards({"emp": employee_id, "user": user["id"]}),
                "menu_defs": menu_defs,
            }
        )

    else:
        today = today_kst().isoformat()
        client_user = conn.execute(
            "SELECT company_id FROM client_users WHERE user_id = ?", (user["id"],)
        ).fetchone()
        company_id = client_user["company_id"] if client_user else None

        todo = []
        recent_requests = []
        today_att = []
        head = {"total": 0, "active": 0, "new_hire": 0, "quit": 0}

        if company_id:
            client_menus = DASH_MENUS["client"]
            todo = [
                ("휴가 승인", _cnt(conn, client_menus["m_leave"][2], company_id), "/client/leave?status=pending", False),
                ("편의지원", _cnt(conn, client_menus["m_accom"][2], company_id), "/client/accommodation?status=pending", False),
                ("증명서 발급", _cnt(conn, client_menus["m_certs"][2], company_id), "/client/certificates", False),
                ("근태 소명", _cnt(conn, client_menus["m_appeals"][2], company_id), "/client/attendance/appeals", False),
                ("결재 대기", _wait_docs(conn, user["id"]), "/approvals?box=wait", False),
                ("이번 달 급여 미확정", _cnt(conn, client_menus["m_payroll"][2], company_id), "/payroll", True),
            ]
            recent_requests = conn.execute(
                "SELECT * FROM work_requests WHERE company_id=? ORDER BY created_at DESC LIMIT 5",
                (company_id,)
            ).fetchall()
            month_start = today_kst().replace(day=1).isoformat()
            head = {
                "total": _cnt(conn, "SELECT COUNT(*) FROM employees WHERE company_id=?", company_id),
                "active": _cnt(conn, "SELECT COUNT(*) FROM employees WHERE company_id=? AND status='active'", company_id),
                "new_hire": _cnt(conn, "SELECT COUNT(*) FROM employees WHERE company_id=? AND hire_date>=?", company_id, month_start),
            }
            head["quit"] = head["total"] - head["active"]
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
                "todo": todo,
                "notices": _notices(conn),
                "head": head,
                "recent_requests": [dict(r) | {"created_date": r["created_at"][:10] if r["created_at"] else "-"} for r in recent_requests],
                "today_att": _att_rows(today_att),
                "att_clocked": len(today_att),
                "task_type_labels": TASK_TYPE_LABELS,
                "request_status_labels": REQUEST_STATUS_LABELS,
                "widgets": widgets,
                "widget_defs": widget_defs,
                "menu_cards": build_menu_cards({"company": company_id}),
                "menu_defs": menu_defs,
            }
        )


@router.post("/dashboard/widgets")
async def save_widgets(request: Request, user: dict = Depends(require_login), conn=Depends(get_db)):
    form = await request.form()
    defs = DASH_WIDGETS.get(user["role"]) or DASH_WIDGETS["client"]
    menu_defs = DASH_MENUS.get(user["role"], {})
    picked = [k for k in list(defs) + list(menu_defs) if k in form]
    conn.execute(
        "INSERT INTO dashboard_prefs (user_id, widgets, updated_at) VALUES (?, ?, datetime('now','localtime')) "
        "ON CONFLICT(user_id) DO UPDATE SET widgets=excluded.widgets, updated_at=excluded.updated_at",
        (user["id"], json.dumps(picked)),
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

