from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.books import seed_accounts
from core.deps import get_db, require_staff, templates
from core.work_schedule import get_schedule

router = APIRouter(prefix="/platform/companies")


@router.get("", response_class=HTMLResponse)
async def company_list(request: Request, q: str = "",
                       u: dict = Depends(require_staff), conn=Depends(get_db)):
    where = "WHERE 1=1"
    params = []
    if q:
        where += " AND (cc.name LIKE ? OR cc.business_no LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]

    sql = f"""
        SELECT
            cc.id, cc.name, cc.business_no, cc.contract_start, cc.contract_end,
            cc.status, cc.contact_name,
            (SELECT COUNT(*) FROM client_users cu WHERE cu.company_id=cc.id) AS mgr_cnt,
            (SELECT COUNT(*) FROM employees e WHERE e.company_id=cc.id) AS emp_cnt,
            (SELECT COUNT(*) FROM work_requests wr
             WHERE wr.company_id=cc.id
               AND wr.status IN ('submitted','review','accepted','in_progress')) AS active_reqs
        FROM client_companies cc
        {where}
        ORDER BY cc.name
    """
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    return templates.TemplateResponse(request=request, name="platform/company_list.html", context={
        "request": request, "page_title": "고객사 관리",
        "user_name": u["name"],
        "companies": rows, "q": q,
    })


@router.get("/new", response_class=HTMLResponse)
async def company_new(request: Request, u: dict = Depends(require_staff)):
    return templates.TemplateResponse(request=request, name="platform/company_form.html", context={
        "request": request, "page_title": "고객사 등록",
        "user_name": u["name"],
        "company": None,
    })


@router.post("", response_class=HTMLResponse)
async def company_create(request: Request,
                         name: str = Form(...),
                         business_no: str = Form(""),
                         representative: str = Form(""),
                         biz_type: str = Form(""),
                         biz_item: str = Form(""),
                         address: str = Form(""),
                         contact_name: str = Form(""),
                         contact_phone: str = Form(""),
                         contact_email: str = Form(""),
                         contract_start: str = Form(""),
                         contract_end: str = Form(""),
                         contract_amount: str = Form(""),
                         contract_content: str = Form(""),
                         u: dict = Depends(require_staff), conn=Depends(get_db)):
    amount = int(contract_amount) if contract_amount.strip() else 0
    cur = conn.execute(
        """INSERT INTO client_companies
           (name, business_no, representative, biz_type, biz_item, address,
            contact_name, contact_phone, contact_email,
            contract_start, contract_end, contract_amount, contract_content)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name, business_no or None, representative, biz_type, biz_item, address,
         contact_name, contact_phone, contact_email,
         contract_start or None, contract_end or None, amount, contract_content),
    )
    seed_accounts(conn, cur.lastrowid)
    conn.commit()
    return RedirectResponse(f"/platform/companies/{cur.lastrowid}", status_code=303)


@router.get("/{cid}", response_class=HTMLResponse)
async def company_detail(request: Request, cid: int,
                         u: dict = Depends(require_staff), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM client_companies WHERE id=?", (cid,)).fetchone()
    if not row:
        return RedirectResponse("/platform/companies", status_code=303)
    company = dict(row)

    # D-day
    dday_label = ""
    if company.get("contract_end"):
        try:
            end = date.fromisoformat(company["contract_end"])
            diff = (end - date.today()).days
            if diff < 0:
                dday_label = "만료"
            elif diff <= 30:
                dday_label = f"D-{diff}"
        except ValueError:
            pass

    managers = [dict(r) for r in conn.execute(
        """SELECT u.id, u.name, u.username, u.role, u.phone, cu.client_role
           FROM client_users cu JOIN users u ON cu.user_id=u.id
           WHERE cu.company_id=?
           ORDER BY u.name""",
        (cid,),
    ).fetchall()]

    # 소속 근로자
    worker_cnt = conn.execute(
        "SELECT COUNT(*) FROM employees WHERE company_id=? AND status='active'", (cid,)
    ).fetchone()[0]
    workers_raw = conn.execute(
        """SELECT id, name, employee_no, position, disability_type, disability_grade, gender
           FROM employees
           WHERE company_id=? AND status='active'
           ORDER BY name LIMIT 10""",
        (cid,),
    ).fetchall()
    gender_map = {"M": "남", "F": "여"}
    workers = []
    for w in workers_raw:
        wd = dict(w)
        parts = [wd.get("disability_type") or "", wd.get("disability_grade") or ""]
        wd["disability_label"] = " ".join(p for p in parts if p) or "-"
        g = wd.get("gender") or ""
        wd["gender_label"] = gender_map.get(g, g or "-")
        workers.append(wd)

    recent_reqs = [dict(r) for r in conn.execute(
        """SELECT id, title, status, created_at
           FROM work_requests
           WHERE company_id=?
           ORDER BY created_at DESC
           LIMIT 5""",
        (cid,),
    ).fetchall()]

    STATUS_LABELS = {
        "draft": "임시저장", "submitted": "접수", "review": "검토중",
        "accepted": "수락", "rejected": "반려", "in_progress": "진행중",
        "completed": "완료", "closed": "마감", "cancelled": "취소",
    }
    STATUS_CLASS = {
        "submitted": "status-badge status-submitted",
        "review": "status-badge status-review",
        "accepted": "status-badge status-accepted",
        "in_progress": "status-badge status-in_progress",
        "completed": "status-badge status-completed",
        "rejected": "status-badge status-rejected",
        "cancelled": "status-badge status-cancelled",
        "closed": "status-badge status-closed",
        "draft": "status-badge status-draft",
    }
    for r in recent_reqs:
        r["status_label"] = STATUS_LABELS.get(r["status"], r["status"])
        r["status_class"] = STATUS_CLASS.get(r["status"], "status-badge status-draft")

    # 업무요청
    req_row = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN status IN ('submitted','review','accepted','in_progress') THEN 1 ELSE 0 END) AS in_prog,
             SUM(CASE WHEN status IN ('completed','closed') THEN 1 ELSE 0 END) AS done
           FROM work_requests WHERE company_id=?""",
        (cid,),
    ).fetchone()
    req_stats = {"total": req_row[0], "in_prog": req_row[1] or 0, "done": req_row[2] or 0}

    # 당월 근태
    cur_ym = date.today().strftime("%Y-%m")
    att_row = conn.execute(
        """SELECT
             SUM(CASE WHEN a.status IN ('normal','late','early_leave','late_early') THEN 1 ELSE 0 END),
             SUM(CASE WHEN a.status IN ('late','late_early') THEN 1 ELSE 0 END),
             SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END)
           FROM attendance a
           JOIN employees e ON a.employee_id=e.id
           WHERE e.company_id=? AND e.status='active'
             AND strftime('%Y-%m', a.work_date)=?""",
        (cid, cur_ym),
    ).fetchone()
    att = {"work_days": att_row[0] or 0, "late": att_row[1] or 0, "absent": att_row[2] or 0}

    # 월간 리포트
    reports = [dict(r) for r in conn.execute(
        """SELECT id, year, month, status
           FROM monthly_reports
           WHERE company_id=?
           ORDER BY year DESC, month DESC LIMIT 6""",
        (cid,),
    ).fetchall()]
    for rp in reports:
        rp["status_label"] = "발행" if rp["status"] == "published" else "작성중"
        rp["status_class"] = "status-badge status-done" if rp["status"] == "published" else "status-badge status-draft"

    return templates.TemplateResponse(request=request, name="platform/company_detail.html", context={
        "request": request, "page_title": company["name"],
        "user_name": u["name"],
        "company": company,
        "dday_label": dday_label,
        "managers": managers,
        "workers": workers,
        "worker_cnt": worker_cnt,
        "recent_reqs": recent_reqs,
        "req_stats": req_stats,
        "att": att,
        "reports": reports,
    })


@router.get("/{cid}/edit", response_class=HTMLResponse)
async def company_edit(request: Request, cid: int,
                       u: dict = Depends(require_staff), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM client_companies WHERE id=?", (cid,)).fetchone()
    if not row:
        return RedirectResponse("/platform/companies", status_code=303)
    sched = get_schedule(conn, cid)
    return templates.TemplateResponse(request=request, name="platform/company_form.html", context={
        "request": request, "page_title": "고객사 수정",
        "user_name": u["name"],
        "company": dict(row),
        "schedule": sched,
    })


@router.post("/{cid}", response_class=HTMLResponse)
async def company_update(request: Request, cid: int,
                         name: str = Form(...),
                         business_no: str = Form(""),
                         representative: str = Form(""),
                         biz_type: str = Form(""),
                         biz_item: str = Form(""),
                         address: str = Form(""),
                         contact_name: str = Form(""),
                         contact_phone: str = Form(""),
                         contact_email: str = Form(""),
                         contract_start: str = Form(""),
                         contract_end: str = Form(""),
                         contract_amount: str = Form(""),
                         contract_content: str = Form(""),
                         status: str = Form("active"),
                         start_time: str = Form("09:00"),
                         end_time: str = Form("18:00"),
                         break_min: int = Form(60),
                         u: dict = Depends(require_staff), conn=Depends(get_db)):
    amount = int(contract_amount) if contract_amount.strip() else 0
    conn.execute(
        """UPDATE client_companies SET
           name=?, business_no=?, representative=?, biz_type=?, biz_item=?, address=?,
           contact_name=?, contact_phone=?, contact_email=?,
           contract_start=?, contract_end=?, contract_amount=?, contract_content=?,
           status=?, updated_at=datetime('now','localtime')
           WHERE id=?""",
        (name, business_no or None, representative, biz_type, biz_item, address,
         contact_name, contact_phone, contact_email,
         contract_start or None, contract_end or None, amount, contract_content,
         status, cid),
    )
    conn.execute(
        """INSERT INTO work_schedules (company_id, start_time, end_time, break_min)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(company_id) DO UPDATE SET
               start_time=excluded.start_time,
               end_time=excluded.end_time,
               break_min=excluded.break_min""",
        (cid, start_time, end_time, break_min),
    )
    conn.commit()
    return RedirectResponse(f"/platform/companies/{cid}", status_code=303)
