from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.db import get_sqlite
from core.deps import check_login, get_current_user, templates
from core.capability import derive_tier2, derive_tier3

router = APIRouter(prefix="/platform")

# task_type 값 → 한국어 레이블
TASK_TYPE_LABELS = {
    "data_entry": "데이터 입력",
    "document_review": "자료 검토",
    "chat_support": "채팅 상담",
    "phone_support": "전화 상담",
    "approval": "결재/전자서명",
    "planning_drafting": "기획/문서 작성",
}

STATUS_LABELS = {
    "pending": "대기",
    "assigned": "배정됨",
    "in_progress": "진행 중",
    "review": "검토 중",
    "completed": "완료",
    "returned": "반려",
    "cancelled": "취소",
}

REQUEST_STATUS_LABELS = {
    "pending": "대기",
    "accepted": "수락",
    "in_progress": "진행 중",
    "completed": "완료",
    "cancelled": "취소",
}


def _require_staff(request: Request):
    if not check_login(request):
        return RedirectResponse(url="/login", status_code=303)
    user = get_current_user(request)
    if user["user_role"] != "platform_staff":
        return RedirectResponse(url="/", status_code=303)
    return None


def _matched_workers(conn, task_type: str, company_id: int | None = None) -> list[dict]:
    # 소속회사 우선, 매칭 우선 정렬
    employees = conn.execute(
        "SELECT e.id, e.name, e.dept, e.position, e.company_id "
        "FROM employees e WHERE e.status='active' ORDER BY e.name"
    ).fetchall()

    same_matched = []
    same_unmatched = []
    other_matched = []
    other_unmatched = []

    for emp in employees:
        profile = conn.execute(
            "SELECT * FROM capability_profiles WHERE employee_id=? "
            "ORDER BY effective_date DESC LIMIT 1",
            (emp["id"],),
        ).fetchone()

        if profile:
            p = dict(profile)
            tier2 = derive_tier2(p)
            tier3 = derive_tier3(tier2, p)
            cap_map = {c["task_key"]: c["feasible"] for c in tier3["capabilities"]}
            is_match = cap_map.get(task_type, False)
        else:
            is_match = False

        is_same = (company_id is not None and emp["company_id"] == company_id)

        row = {
            "id": emp["id"],
            "name": emp["name"],
            "dept": emp["dept"],
            "position": emp["position"],
            "matched": is_match,
            "has_profile": profile is not None,
            "same_company": is_same,
        }

        if is_same:
            if is_match:
                same_matched.append(row)
            else:
                same_unmatched.append(row)
        else:
            if is_match:
                other_matched.append(row)
            else:
                other_unmatched.append(row)

    return same_matched + same_unmatched + other_matched + other_unmatched


@router.get("/work-requests", response_class=HTMLResponse)
async def work_request_list(request: Request, status: str = ""):
    guard = _require_staff(request)
    if guard:
        return guard
    user = get_current_user(request)

    conn = get_sqlite()
    try:
        sql = (
            "SELECT wr.*, cc.name AS company_name, "
            "  (SELECT COUNT(*) FROM tasks t WHERE t.work_request_id=wr.id) AS task_total, "
            "  (SELECT COUNT(*) FROM tasks t WHERE t.work_request_id=wr.id AND t.status='pending') AS task_pending, "
            "  (SELECT COUNT(*) FROM tasks t WHERE t.work_request_id=wr.id AND t.status='assigned') AS task_assigned, "
            "  (SELECT COUNT(*) FROM tasks t WHERE t.work_request_id=wr.id AND t.status='in_progress') AS task_in_progress, "
            "  (SELECT COUNT(*) FROM tasks t WHERE t.work_request_id=wr.id AND t.status='review') AS task_review, "
            "  (SELECT COUNT(*) FROM tasks t WHERE t.work_request_id=wr.id AND t.status='completed') AS task_completed "
            "FROM work_requests wr "
            "JOIN client_companies cc ON wr.company_id=cc.id "
        )
        params: list = []
        if status:
            sql += "WHERE wr.status=? "
            params.append(status)
        sql += "ORDER BY wr.created_at DESC"
        requests_list = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="platform/work_request_list.html",
        context={
            "request": request,
            "page_title": "업무 요청 관리",
            "user_name": user["user_name"],
            "user_role": user["user_role"],
            "requests_list": [dict(r) for r in requests_list],
            "selected_status": status,
            "task_type_labels": TASK_TYPE_LABELS,
            "request_status_labels": REQUEST_STATUS_LABELS,
        },
    )


@router.get("/work-requests/{req_id}", response_class=HTMLResponse)
async def work_request_detail(request: Request, req_id: int):
    guard = _require_staff(request)
    if guard:
        return guard
    user = get_current_user(request)

    conn = get_sqlite()
    try:
        work_req = conn.execute(
            "SELECT wr.*, cc.name AS company_name "
            "FROM work_requests wr JOIN client_companies cc ON wr.company_id=cc.id "
            "WHERE wr.id=?",
            (req_id,),
        ).fetchone()
        if not work_req:
            return RedirectResponse(url="/platform/work-requests", status_code=303)

        tasks = conn.execute(
            "SELECT t.*, e.name AS worker_name "
            "FROM tasks t LEFT JOIN employees e ON t.assigned_to=e.id "
            "WHERE t.work_request_id=? ORDER BY t.created_at DESC",
            (req_id,),
        ).fetchall()

        workers = _matched_workers(conn, work_req["task_type"], work_req["company_id"])
    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="platform/work_request_detail.html",
        context={
            "request": request,
            "page_title": f"{work_req['title']} - 요청 상세",
            "user_name": user["user_name"],
            "user_role": user["user_role"],
            "work_req": dict(work_req),
            "tasks": [dict(t) for t in tasks],
            "workers": workers,
            "task_type_labels": TASK_TYPE_LABELS,
            "status_labels": STATUS_LABELS,
            "request_status_labels": REQUEST_STATUS_LABELS,
        },
    )


@router.post("/work-requests/{req_id}/tasks/new")
async def task_create(
    request: Request,
    req_id: int,
    title: str = Form(...),
    description: str = Form(""),
    due_date: str = Form(""),
    split_count: int = Form(1),
):
    guard = _require_staff(request)
    if guard:
        return guard
    user = get_current_user(request)

    conn = get_sqlite()
    try:
        work_req = conn.execute(
            "SELECT * FROM work_requests WHERE id=?", (req_id,)
        ).fetchone()
        if not work_req:
            return RedirectResponse(url="/platform/work-requests", status_code=303)

        # split_count가 1보다 크면 같은 제목에 번호를 붙여 여러 태스크 생성
        count = max(1, min(split_count, 100))
        eff_due = due_date or work_req["due_date"] or ""

        for i in range(count):
            task_title = f"{title} ({i+1}/{count})" if count > 1 else title
            conn.execute(
                "INSERT INTO tasks (work_request_id, title, description, task_type, status, priority, due_date, assigned_by) "
                "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
                (req_id, task_title, description, work_req["task_type"],
                 work_req["priority"], eff_due or None, user["user_id"]),
            )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url=f"/platform/work-requests/{req_id}", status_code=303)


@router.post("/work-requests/{req_id}/tasks/{task_id}/assign")
async def task_assign(
    request: Request,
    req_id: int,
    task_id: int,
    employee_id: str = Form(""),
):
    guard = _require_staff(request)
    if guard:
        return guard
    user = get_current_user(request)

    conn = get_sqlite()
    try:
        task = conn.execute(
            "SELECT * FROM tasks WHERE id=? AND work_request_id=?", (task_id, req_id)
        ).fetchone()
        if not task or task["status"] not in ("pending", "assigned"):
            return RedirectResponse(url=f"/platform/work-requests/{req_id}", status_code=303)

        if employee_id:
            # 담당자 지정 → status를 assigned로
            conn.execute(
                "UPDATE tasks SET assigned_to=?, assigned_by=?, status='assigned', "
                "updated_at=datetime('now','localtime') WHERE id=?",
                (int(employee_id), user["user_id"], task_id),
            )
        else:
            # 배정 해제 → pending으로 되돌림
            conn.execute(
                "UPDATE tasks SET assigned_to=NULL, status='pending', "
                "updated_at=datetime('now','localtime') WHERE id=?",
                (task_id,),
            )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url=f"/platform/work-requests/{req_id}", status_code=303)
