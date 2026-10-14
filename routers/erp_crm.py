import calendar as cal_mod
from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core.deps import get_db, templates
from core.erp_log import log_activity
from core.tz import today_kst
from core.books import require_book, book_users
from core import partner
from core.crm import LEAD_STATUS, LEAD_CLASS, STAGES, STAGE_PROB, STAGE_CLASS, ACT_KINDS
from routers.erp_master import PER_PAGE, norm_biz_no, dup_partners, _own
from routers.erp_sales import QT_STATUS

router = APIRouter()

OPEN_STAGES = ("found", "proposal", "nego")


def _page(conn, sql, args, page):
    total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, pages))
    rows = [dict(r) for r in conn.execute(f"{sql} LIMIT {PER_PAGE} OFFSET {(page - 1) * PER_PAGE}", args)]
    return rows, {"page": page, "total_pages": pages, "total_count": total}


def _rep(conn, book, rep_id):
    return rep_id if rep_id in {r["id"] for r in book_users(conn, book)} else None


def _day(v, label):
    if not v:
        return ""
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError(f"{label}를 확인해 주세요.")


# 영업활동

@router.get("/crm/activities", response_class=HTMLResponse)
async def act_list(request: Request, q: str = "", kind: str = "", rep: int = 0, date_from: str = "",
                   date_to: str = "", partner_id: int = 0, contact_id: int = 0, view: str = "", page: int = 1,
                   u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    today = today_kst().isoformat()
    where, args = ["a.company_id=?"], [book]
    if view == "due":
        where.append("a.next_date!='' AND a.next_done=0 AND a.next_date<=?")
        args.append(today)
    if q:
        where.append("(a.subject LIKE ? OR a.content LIKE ? OR p.name LIKE ? OR l.name LIKE ?)")
        args += [f"%{q}%"] * 4
    if kind in ACT_KINDS:
        where.append("a.kind=?")
        args.append(kind)
    if rep:
        where.append("a.rep_id=?")
        args.append(rep)
    if partner_id:
        where.append("a.partner_id=?")
        args.append(partner_id)
    if contact_id:
        where.append("a.contact_id=?")
        args.append(contact_id)
    if date_from:
        where.append("a.act_date>=?")
        args.append(date_from)
    if date_to:
        where.append("a.act_date<=?")
        args.append(date_to)
    order = "a.next_date, a.id" if view == "due" else "a.act_date DESC, a.id DESC"
    rows, pg = _page(conn, f"""
        SELECT a.*, p.name AS partner_name, l.name AS lead_name, o.title AS opp_title, ru.name AS rep_name,
               pc.name AS contact_name
        FROM crm_activities a
        LEFT JOIN partners p ON p.id=a.partner_id
        LEFT JOIN crm_leads l ON l.id=a.lead_id
        LEFT JOIN crm_opps o ON o.id=a.opp_id
        LEFT JOIN users ru ON ru.id=a.rep_id
        LEFT JOIN partner_contacts pc ON pc.id=a.contact_id
        WHERE {' AND '.join(where)} ORDER BY {order}""", args, page)
    due_cnt = conn.execute(
        "SELECT COUNT(*) FROM crm_activities WHERE company_id=? AND next_date!='' AND next_done=0 AND next_date<=?",
        (book, today)).fetchone()[0]
    qs = urlencode({"q": q, "kind": kind, "rep": rep, "date_from": date_from, "date_to": date_to,
                    "partner_id": partner_id, "contact_id": contact_id, "view": view})
    return templates.TemplateResponse(request=request, name="erp/crm_activity_list.html", context={
        "request": request, "page_title": "영업활동",
        "user_name": u["name"],
        "rows": rows, "q": q, "kind": kind, "rep": rep, "date_from": date_from, "date_to": date_to,
        "partner_id": partner_id, "contact_id": contact_id, "view": view, "today": today, "due_cnt": due_cnt,
        "kinds": ACT_KINDS, "reps": book_users(conn, book), "base_url": f"/crm/activities?{qs}", **pg,
    })


def _act_form(request, u, conn, act):
    book = u["book"]
    target = None
    if act.get("partner_id"):
        target = conn.execute("SELECT id, code, name FROM partners WHERE id=? AND company_id=?",
                              (act["partner_id"], book)).fetchone()
    lead = None
    if act.get("lead_id"):
        lead = conn.execute("SELECT id, name FROM crm_leads WHERE id=? AND company_id=?",
                            (act["lead_id"], book)).fetchone()
    opps = conn.execute(
        """SELECT id, title FROM crm_opps WHERE company_id=? AND (partner_id=? OR lead_id=?)
           AND (stage IN ('found','proposal','nego') OR id=?) ORDER BY id DESC""",
        (book, act.get("partner_id") or 0, act.get("lead_id") or 0, act.get("opp_id") or 0)).fetchall()
    leads = conn.execute("SELECT id, name FROM crm_leads WHERE company_id=? AND status NOT IN ('converted','lost') ORDER BY name",
                         (book,)).fetchall()
    return templates.TemplateResponse(request=request, name="erp/crm_activity_form.html", context={
        "request": request, "page_title": "영업활동 수정" if act.get("id") else "영업활동 등록",
        "user_name": u["name"], "can_edit": partner.can_edit(u),
        "act": act, "partner": target, "lead": lead, "opps": opps, "leads": leads,
        "kinds": ACT_KINDS, "reps": book_users(conn, book),
    })


@router.get("/crm/activities/new", response_class=HTMLResponse)
async def act_new(request: Request, partner_id: int = 0, lead_id: int = 0, opp_id: int = 0,
                  u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    opp = conn.execute("SELECT id, partner_id, lead_id FROM crm_opps WHERE id=? AND company_id=?",
                       (opp_id, book)).fetchone() if opp_id else None
    if opp:
        partner_id, lead_id = opp["partner_id"] or 0, opp["lead_id"] or 0
    act = {"partner_id": partner_id, "lead_id": 0 if partner_id else lead_id, "opp_id": opp_id if opp else 0,
           "kind": "call", "act_date": today_kst().isoformat(), "rep_id": u["id"]}
    return _act_form(request, u, conn, act)


@router.get("/crm/activities/{act_id}/edit", response_class=HTMLResponse)
async def act_edit(request: Request, act_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM crm_activities WHERE id=? AND company_id=?", (act_id, u["book"])).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    return _act_form(request, u, conn, dict(row))


@router.post("/crm/activities/save")
async def act_save(act_id: int = Form(0), partner_id: int = Form(0), lead_id: int = Form(0), opp_id: int = Form(0),
                   contact_id: int = Form(0),
                   kind: str = Form("call"), act_date: str = Form(""), subject: str = Form(""),
                   content: str = Form(""), rep_id: int = Form(0), next_date: str = Form(""),
                   next_action: str = Form(""), next_done: int = Form(0),
                   u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    subject = subject.strip()
    if not subject:
        return JSONResponse({"error": "제목을 입력해 주세요."}, status_code=400)
    if kind not in ACT_KINDS:
        return JSONResponse({"error": "활동구분을 확인해 주세요."}, status_code=400)
    try:
        act_date = _day(act_date, "활동일") or today_kst().isoformat()
        next_date = _day(next_date, "다음 일정일")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if next_date and next_date < act_date:
        return JSONResponse({"error": "다음 일정일은 활동일 이후로 입력해 주세요."}, status_code=400)
    partner_id = _own(conn, "partners", partner_id, book)
    lead_id = None if partner_id else _own(conn, "crm_leads", lead_id, book)
    if not partner_id and not lead_id:
        return JSONResponse({"error": "거래처 또는 잠재고객을 선택해 주세요."}, status_code=400)
    contact_id = partner.own_contact(conn, book, partner_id, contact_id)
    if opp_id and partner_id:
        opp = conn.execute("SELECT id FROM crm_opps WHERE id=? AND company_id=? AND partner_id=?",
                           (opp_id, book, partner_id)).fetchone()
    elif opp_id:
        opp = conn.execute("SELECT id FROM crm_opps WHERE id=? AND company_id=? AND lead_id=? AND partner_id IS NULL",
                           (opp_id, book, lead_id)).fetchone()
    else:
        opp = None
    vals = (partner_id, lead_id, opp["id"] if opp else None, contact_id, kind, act_date, subject, content.strip(),
            _rep(conn, book, rep_id), next_date, next_action.strip(), 1 if next_done and next_date else 0)
    if act_id:
        cur = conn.execute(
            """UPDATE crm_activities SET partner_id=?, lead_id=?, opp_id=?, contact_id=?, kind=?, act_date=?, subject=?,
               content=?, rep_id=?, next_date=?, next_action=?, next_done=? WHERE id=? AND company_id=?""",
            (*vals, act_id, book))
        if not cur.rowcount:
            raise HTTPException(status_code=404)
        log_activity(conn, u["id"], "update", "crm", act_id, "", f"영업활동 수정 {subject}")
    else:
        act_id = conn.execute(
            """INSERT INTO crm_activities (partner_id, lead_id, opp_id, contact_id, kind, act_date, subject, content,
               rep_id, next_date, next_action, next_done, company_id, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*vals, book, u["id"])).lastrowid
        log_activity(conn, u["id"], "create", "crm", act_id, "", f"영업활동 등록 {subject}")
    # 활동이 생긴 신규 잠재고객은 접촉중으로 진행
    if lead_id:
        conn.execute("UPDATE crm_leads SET status='contact' WHERE id=? AND status='new'", (lead_id,))
    conn.commit()
    if partner_id:
        return RedirectResponse(f"/partners/{partner_id}#tabActs", status_code=303)
    return RedirectResponse(f"/crm/leads/{lead_id}", status_code=303)


@router.post("/crm/activities/{act_id}/delete")
async def act_delete(act_id: int, u: dict = Depends(partner.require_editor), conn=Depends(get_db)):
    row = conn.execute("SELECT subject FROM crm_activities WHERE id=? AND company_id=?",
                       (act_id, u["book"])).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    conn.execute("DELETE FROM crm_activities WHERE id=?", (act_id,))
    log_activity(conn, u["id"], "delete", "crm", act_id, "", f"영업활동 삭제 {row['subject']}")
    conn.commit()
    return RedirectResponse("/crm/activities", status_code=303)


@router.post("/crm/activities/{act_id}/done")
async def act_done(request: Request, act_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    conn.execute("UPDATE crm_activities SET next_done=1 WHERE id=? AND company_id=? AND next_date!=''",
                 (act_id, u["book"]))
    conn.commit()
    back = request.headers.get("referer", "")
    return RedirectResponse(back if back.startswith(str(request.base_url)) else "/crm/activities?view=due",
                            status_code=303)


# 잠재고객

@router.get("/crm/leads", response_class=HTMLResponse)
async def lead_list(request: Request, q: str = "", status: str = "", rep: int = 0, page: int = 1,
                    u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    where, args = ["l.company_id=?"], [book]
    if status in LEAD_STATUS:
        where.append("l.status=?")
        args.append(status)
    else:
        status = ""
        where.append("l.status NOT IN ('converted','lost')")
    if q:
        where.append("(l.name LIKE ? OR l.contact_name LIKE ? OR l.phone LIKE ? OR l.biz_no LIKE ?)")
        args += [f"%{q}%"] * 4
    if rep:
        where.append("l.rep_id=?")
        args.append(rep)
    rows, pg = _page(conn, f"""
        SELECT l.*, ru.name AS rep_name,
               (SELECT MAX(act_date) FROM crm_activities WHERE lead_id=l.id) AS last_act,
               (SELECT MIN(next_date) FROM crm_activities WHERE lead_id=l.id AND next_date!='' AND next_done=0) AS next_date
        FROM crm_leads l LEFT JOIN users ru ON ru.id=l.rep_id
        WHERE {' AND '.join(where)} ORDER BY l.id DESC""", args, page)
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM crm_leads WHERE company_id=? GROUP BY status",
                               (book,)).fetchall())
    qs = urlencode({"q": q, "status": status, "rep": rep})
    return templates.TemplateResponse(request=request, name="erp/crm_lead_list.html", context={
        "request": request, "page_title": "잠재고객",
        "user_name": u["name"],
        "rows": rows, "q": q, "status": status, "rep": rep, "counts": counts,
        "statuses": LEAD_STATUS, "lead_class": LEAD_CLASS, "reps": book_users(conn, book), "base_url": f"/crm/leads?{qs}", **pg,
    })


def _lead_form(request, u, conn, lead):
    return templates.TemplateResponse(request=request, name="erp/crm_lead_form.html", context={
        "request": request, "page_title": "잠재고객 수정" if lead.get("id") else "잠재고객 등록",
        "user_name": u["name"],
        "lead": lead, "statuses": {k: v for k, v in LEAD_STATUS.items() if k != "converted"},
        "reps": book_users(conn, u["book"]),
    })


@router.get("/crm/leads/new", response_class=HTMLResponse)
async def lead_new(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    return _lead_form(request, u, conn, {"status": "new", "rep_id": u["id"]})


@router.get("/crm/leads/{lead_id}/edit", response_class=HTMLResponse)
async def lead_edit(request: Request, lead_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM crm_leads WHERE id=? AND company_id=?", (lead_id, u["book"])).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    if row["status"] == "converted":
        return RedirectResponse(f"/crm/leads/{lead_id}", status_code=303)
    return _lead_form(request, u, conn, dict(row))


@router.post("/crm/leads/save")
async def lead_save(lead_id: int = Form(0), name: str = Form(""), contact_name: str = Form(""),
                    phone: str = Form(""), email: str = Form(""), biz_no: str = Form(""), address: str = Form(""),
                    source: str = Form(""), status: str = Form("new"), rep_id: int = Form(0), notes: str = Form(""),
                    u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    name = name.strip()
    if not name:
        return JSONResponse({"error": "업체명을 입력해 주세요."}, status_code=400)
    if status not in LEAD_STATUS or status == "converted":
        return JSONResponse({"error": "진행상태를 확인해 주세요."}, status_code=400)
    biz_no = norm_biz_no(biz_no)
    if biz_no is None:
        return JSONResponse({"error": "사업자번호가 올바르지 않습니다."}, status_code=400)
    vals = (name, contact_name.strip(), phone.strip(), email.strip(), biz_no, address.strip(), source.strip(),
            status, _rep(conn, book, rep_id), notes.strip())
    if lead_id:
        cur = conn.execute(
            """UPDATE crm_leads SET name=?, contact_name=?, phone=?, email=?, biz_no=?, address=?, source=?,
               status=?, rep_id=?, notes=? WHERE id=? AND company_id=? AND status!='converted'""",
            (*vals, lead_id, book))
        if not cur.rowcount:
            return JSONResponse({"error": "거래처로 전환된 잠재고객은 수정할 수 없습니다."}, status_code=400)
        log_activity(conn, u["id"], "update", "crm", lead_id, "", f"잠재고객 수정 {name}")
    else:
        lead_id = conn.execute(
            """INSERT INTO crm_leads (name, contact_name, phone, email, biz_no, address, source, status, rep_id,
               notes, company_id, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*vals, book, u["id"])).lastrowid
        log_activity(conn, u["id"], "create", "crm", lead_id, "", f"잠재고객 등록 {name}")
    conn.commit()
    return RedirectResponse(f"/crm/leads/{lead_id}", status_code=303)


@router.get("/crm/leads/{lead_id}", response_class=HTMLResponse)
async def lead_detail(request: Request, lead_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    lead = conn.execute(
        """SELECT l.*, ru.name AS rep_name, p.name AS partner_name FROM crm_leads l
           LEFT JOIN users ru ON ru.id=l.rep_id LEFT JOIN partners p ON p.id=l.partner_id
           WHERE l.id=? AND l.company_id=?""", (lead_id, book)).fetchone()
    if not lead:
        raise HTTPException(status_code=404)
    acts = conn.execute(
        """SELECT a.*, ru.name AS rep_name, pc.name AS contact_name FROM crm_activities a
           LEFT JOIN users ru ON ru.id=a.rep_id LEFT JOIN partner_contacts pc ON pc.id=a.contact_id
           WHERE a.company_id=? AND (a.lead_id=? OR (a.partner_id IS NOT NULL AND a.partner_id=?))
           ORDER BY a.act_date DESC, a.id DESC""", (book, lead_id, lead["partner_id"])).fetchall()
    opps = conn.execute(
        """SELECT o.*, ru.name AS rep_name FROM crm_opps o LEFT JOIN users ru ON ru.id=o.rep_id
           WHERE o.company_id=? AND o.lead_id=? ORDER BY o.id DESC""", (book, lead_id)).fetchall()
    return templates.TemplateResponse(request=request, name="erp/crm_lead_detail.html", context={
        "request": request, "page_title": "잠재고객",
        "user_name": u["name"], "can_edit": partner.can_edit(u),
        "lead": lead, "acts": acts, "opps": opps, "statuses": LEAD_STATUS, "stages": STAGES,
        "lead_class": LEAD_CLASS, "stage_class": STAGE_CLASS, "kinds": ACT_KINDS,
        "dups": dup_partners(conn, book, lead["biz_no"]) if lead["status"] != "converted" else [],
    })


# 신규 거래처 생성 또는 사업자번호 일치 거래처에 연결. 활동, 영업기회도 거래처로 이관
@router.post("/crm/leads/{lead_id}/convert")
async def lead_convert(request: Request, lead_id: int, partner_id: int = Form(0),
                       u: dict = Depends(partner.require_editor), conn=Depends(get_db)):
    book = u["book"]
    lead = conn.execute("SELECT * FROM crm_leads WHERE id=? AND company_id=?", (lead_id, book)).fetchone()
    if not lead:
        raise HTTPException(status_code=404)
    if lead["status"] == "converted":
        return RedirectResponse(f"/partners/{lead['partner_id']}", status_code=303)
    if partner_id:
        p = conn.execute("SELECT id, partner_type FROM partners WHERE id=? AND company_id=?",
                         (partner_id, book)).fetchone()
        if not p:
            raise HTTPException(status_code=404)
        if p["partner_type"] == "supplier":
            conn.execute("UPDATE partners SET partner_type='both' WHERE id=?", (partner_id,))
        pid, created = partner_id, False
    else:
        last = conn.execute(
            "SELECT code FROM partners WHERE company_id=? AND code GLOB '[0-9][0-9][0-9][0-9][0-9]' ORDER BY code DESC LIMIT 1",
            (book,)).fetchone()
        code = f"{(int(last['code']) + 1) if last else 1:05d}"
        pid = conn.execute(
            """INSERT INTO partners (company_id, code, name, partner_type, biz_no, address, phone, email, rep_id,
               notes, created_by) VALUES (?,?,?,'customer',?,?,?,?,?,?,?)""",
            (book, code, lead["name"], lead["biz_no"], lead["address"], lead["phone"], lead["email"],
             lead["rep_id"], lead["notes"], u["id"])).lastrowid
        if lead["contact_name"]:
            conn.execute(
                """INSERT INTO partner_contacts (company_id, partner_id, name, mobile, email, is_primary, is_active)
                   VALUES (?,?,?,?,?,1,1)""",
                (book, pid, lead["contact_name"], lead["phone"], lead["email"]))
        created = True
    conn.execute("UPDATE crm_leads SET status='converted', partner_id=? WHERE id=?", (pid, lead_id))
    conn.execute("UPDATE crm_activities SET partner_id=?, lead_id=NULL WHERE lead_id=? AND company_id=?",
                 (pid, lead_id, book))
    conn.execute("UPDATE crm_opps SET partner_id=? WHERE lead_id=? AND company_id=?", (pid, lead_id, book))
    log_activity(conn, u["id"], "update", "crm", lead_id, "", f"잠재고객 거래처 전환 {lead['name']}")
    conn.commit()
    # 신규 거래처는 사업자 정보 보완을 위해 수정 화면으로 이동
    return RedirectResponse(f"/partners/{pid}/edit" if created else f"/partners/{pid}", status_code=303)


@router.post("/crm/leads/{lead_id}/delete")
async def lead_delete(lead_id: int, u: dict = Depends(partner.require_editor), conn=Depends(get_db)):
    book = u["book"]
    lead = conn.execute("SELECT name, status FROM crm_leads WHERE id=? AND company_id=?", (lead_id, book)).fetchone()
    if not lead:
        raise HTTPException(status_code=404)
    if lead["status"] == "converted" or conn.execute("SELECT 1 FROM crm_opps WHERE lead_id=?", (lead_id,)).fetchone():
        return JSONResponse({"error": "영업기회가 있거나 거래처로 전환된 잠재고객은 삭제할 수 없습니다. 진행상태를 종료로 바꿔 주세요."},
                            status_code=400)
    conn.execute("DELETE FROM crm_activities WHERE lead_id=?", (lead_id,))
    conn.execute("DELETE FROM crm_leads WHERE id=?", (lead_id,))
    log_activity(conn, u["id"], "delete", "crm", lead_id, "", f"잠재고객 삭제 {lead['name']}")
    conn.commit()
    return RedirectResponse("/crm/leads", status_code=303)


# 영업기회

@router.get("/crm/opps", response_class=HTMLResponse)
async def opp_list(request: Request, q: str = "", stage: str = "", rep: int = 0, view: str = "board",
                   page: int = 1, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    where, args = ["o.company_id=?"], [book]
    if q:
        where.append("(o.title LIKE ? OR p.name LIKE ? OR l.name LIKE ?)")
        args += [f"%{q}%"] * 3
    if rep:
        where.append("o.rep_id=?")
        args.append(rep)
    sql = f"""SELECT o.*, COALESCE(p.name, l.name) AS cust_name, ru.name AS rep_name, qt.quote_number
              FROM crm_opps o
              LEFT JOIN partners p ON p.id=o.partner_id
              LEFT JOIN crm_leads l ON l.id=o.lead_id
              LEFT JOIN users ru ON ru.id=o.rep_id
              LEFT JOIN quotations qt ON qt.id=o.quote_id
              WHERE {' AND '.join(where)}"""
    ctx = {}
    if view == "list":
        if stage in STAGES:
            sql += " AND o.stage=?"
            args.append(stage)
        rows, pg = _page(conn, sql + " ORDER BY o.id DESC", args, page)
        ctx.update(rows=rows, **pg)
    else:
        view = "board"
        # 종료 단계는 최근 90일 마감분만
        since = date.fromordinal(today_kst().toordinal() - 90).isoformat()
        rows = conn.execute(
            sql + " AND (o.stage IN ('found','proposal','nego') OR o.closed_at>=?)"
                  " ORDER BY CASE WHEN o.close_date='' THEN 1 ELSE 0 END, o.close_date, o.id",
            (*args, since)).fetchall()
        cols = {k: {"label": v, "rows": [], "amount": 0} for k, v in STAGES.items()}
        for r in rows:
            cols[r["stage"]]["rows"].append(r)
            cols[r["stage"]]["amount"] += r["amount"]
        ctx["cols"] = cols
    qs = urlencode({"q": q, "stage": stage, "rep": rep, "view": view})
    return templates.TemplateResponse(request=request, name="erp/crm_opp_list.html", context={
        "request": request, "page_title": "영업기회",
        "user_name": u["name"],
        "q": q, "stage": stage, "rep": rep, "view": view, "today": today_kst().isoformat(),
        "stages": STAGES, "stage_class": STAGE_CLASS, "reps": book_users(conn, book), "base_url": f"/crm/opps?{qs}", **ctx,
    })


def _opp_form(request, u, conn, opp):
    book = u["book"]
    partner = conn.execute("SELECT id, code, name FROM partners WHERE id=? AND company_id=?",
                           (opp.get("partner_id") or 0, book)).fetchone()
    leads = conn.execute(
        "SELECT id, name FROM crm_leads WHERE company_id=? AND (status NOT IN ('converted','lost') OR id=?) ORDER BY name",
        (book, opp.get("lead_id") or 0)).fetchall()
    return templates.TemplateResponse(request=request, name="erp/crm_opp_form.html", context={
        "request": request, "page_title": "영업기회 수정" if opp.get("id") else "영업기회 등록",
        "user_name": u["name"],
        "opp": opp, "partner": partner, "leads": leads,
        "stages": {k: v for k, v in STAGES.items() if k in OPEN_STAGES}, "reps": book_users(conn, book),
    })


@router.get("/crm/opps/new", response_class=HTMLResponse)
async def opp_new(request: Request, partner_id: int = 0, lead_id: int = 0,
                  u: dict = Depends(require_book), conn=Depends(get_db)):
    return _opp_form(request, u, conn, {"partner_id": partner_id, "lead_id": 0 if partner_id else lead_id,
                                        "stage": "found", "amount": 0, "rep_id": u["id"]})


@router.get("/crm/opps/{opp_id}/edit", response_class=HTMLResponse)
async def opp_edit(request: Request, opp_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    row = conn.execute("SELECT * FROM crm_opps WHERE id=? AND company_id=?", (opp_id, u["book"])).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    if row["stage"] in ("won", "lost"):
        return RedirectResponse(f"/crm/opps/{opp_id}", status_code=303)
    return _opp_form(request, u, conn, dict(row))


@router.post("/crm/opps/save")
async def opp_save(opp_id: int = Form(0), title: str = Form(""), partner_id: int = Form(0), lead_id: int = Form(0),
                   stage: str = Form("found"), amount: str = Form("0"), close_date: str = Form(""),
                   rep_id: int = Form(0), notes: str = Form(""),
                   u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    title = title.strip()
    amt = amount.replace(",", "") or "0"
    if not title:
        return JSONResponse({"error": "영업기회명을 입력해 주세요."}, status_code=400)
    if stage not in OPEN_STAGES:
        return JSONResponse({"error": "진행단계를 확인해 주세요."}, status_code=400)
    if not amt.isdigit():
        return JSONResponse({"error": "예상금액은 0 이상 숫자로 입력해 주세요."}, status_code=400)
    try:
        close_date = _day(close_date, "예상 마감일")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    partner_id = _own(conn, "partners", partner_id, book)
    lead_id = None if partner_id else _own(conn, "crm_leads", lead_id, book)
    if not partner_id and not lead_id:
        return JSONResponse({"error": "거래처 또는 잠재고객을 선택해 주세요."}, status_code=400)
    vals = (title, partner_id, lead_id, stage, int(amt), close_date, _rep(conn, book, rep_id), notes.strip())
    if opp_id:
        cur = conn.execute(
            """UPDATE crm_opps SET title=?, partner_id=?, lead_id=?, stage=?, amount=?, close_date=?, rep_id=?, notes=?
               WHERE id=? AND company_id=? AND stage IN ('found','proposal','nego')""", (*vals, opp_id, book))
        if not cur.rowcount:
            return JSONResponse({"error": "종료된 영업기회는 수정할 수 없습니다."}, status_code=400)
        log_activity(conn, u["id"], "update", "crm", opp_id, "", f"영업기회 수정 {title}")
    else:
        opp_id = conn.execute(
            """INSERT INTO crm_opps (title, partner_id, lead_id, stage, amount, close_date, rep_id, notes,
               company_id, created_by) VALUES (?,?,?,?,?,?,?,?,?,?)""", (*vals, book, u["id"])).lastrowid
        log_activity(conn, u["id"], "create", "crm", opp_id, "", f"영업기회 등록 {title}")
    conn.commit()
    return RedirectResponse(f"/crm/opps/{opp_id}", status_code=303)


@router.get("/crm/opps/{opp_id}", response_class=HTMLResponse)
async def opp_detail(request: Request, opp_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    opp = conn.execute(
        """SELECT o.*, p.name AS partner_name, l.name AS lead_name, ru.name AS rep_name,
                  qt.quote_number, qt.status AS quote_status, qt.total_amount + qt.tax_amount AS quote_total
           FROM crm_opps o
           LEFT JOIN partners p ON p.id=o.partner_id
           LEFT JOIN crm_leads l ON l.id=o.lead_id
           LEFT JOIN users ru ON ru.id=o.rep_id
           LEFT JOIN quotations qt ON qt.id=o.quote_id
           WHERE o.id=? AND o.company_id=?""", (opp_id, book)).fetchone()
    if not opp:
        raise HTTPException(status_code=404)
    acts = conn.execute(
        """SELECT a.*, ru.name AS rep_name, pc.name AS contact_name FROM crm_activities a
           LEFT JOIN users ru ON ru.id=a.rep_id LEFT JOIN partner_contacts pc ON pc.id=a.contact_id
           WHERE a.company_id=? AND a.opp_id=? ORDER BY a.act_date DESC, a.id DESC""", (book, opp_id)).fetchall()
    return templates.TemplateResponse(request=request, name="erp/crm_opp_detail.html", context={
        "request": request, "page_title": "영업기회",
        "user_name": u["name"], "can_edit": partner.can_edit(u),
        "opp": opp, "acts": acts, "stages": STAGES, "stage_class": STAGE_CLASS, "probs": STAGE_PROB, "kinds": ACT_KINDS,
        "qt_status": QT_STATUS,
    })


@router.post("/crm/opps/{opp_id}/stage")
async def opp_stage(opp_id: int, stage: str = Form(...), lost_reason: str = Form(""),
                    u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    opp = conn.execute(
        """SELECT o.title, o.stage, qt.status AS quote_status FROM crm_opps o
           LEFT JOIN quotations qt ON qt.id=o.quote_id WHERE o.id=? AND o.company_id=?""", (opp_id, book)).fetchone()
    if not opp or stage not in STAGES:
        raise HTTPException(status_code=404)
    # 종료 건은 재진행을 거쳐야 재종료 가능. 수주 전환된 건과 비편집자는 재진행 불가
    if opp["stage"] in ("won", "lost"):
        if stage in ("won", "lost"):
            return JSONResponse({"error": "종료된 영업기회입니다. 다시 진행한 뒤 종료해 주세요."}, status_code=400)
        if not partner.can_edit(u):
            raise HTTPException(status_code=403)
        if opp["quote_status"] == "accepted":
            return JSONResponse({"error": "수주로 전환된 영업기회는 다시 진행할 수 없습니다."}, status_code=400)
    if stage == "lost" and not lost_reason.strip():
        return JSONResponse({"error": "실패 사유를 입력해 주세요."}, status_code=400)
    closed = today_kst().isoformat() if stage in ("won", "lost") else ""
    conn.execute("UPDATE crm_opps SET stage=?, closed_at=?, lost_reason=? WHERE id=?",
                 (stage, closed, lost_reason.strip() if stage == "lost" else "", opp_id))
    log_activity(conn, u["id"], "update", "crm", opp_id, "",
                 f"영업기회 단계 {opp['title']} {STAGES[opp['stage']]} > {STAGES[stage]}")
    conn.commit()
    return RedirectResponse(f"/crm/opps/{opp_id}", status_code=303)


@router.post("/crm/opps/{opp_id}/delete")
async def opp_delete(opp_id: int, u: dict = Depends(partner.require_editor), conn=Depends(get_db)):
    book = u["book"]
    opp = conn.execute("SELECT title FROM crm_opps WHERE id=? AND company_id=?", (opp_id, book)).fetchone()
    if not opp:
        raise HTTPException(status_code=404)
    conn.execute("UPDATE crm_activities SET opp_id=NULL WHERE opp_id=?", (opp_id,))
    conn.execute("DELETE FROM crm_opps WHERE id=?", (opp_id,))
    log_activity(conn, u["id"], "delete", "crm", opp_id, "", f"영업기회 삭제 {opp['title']}")
    conn.commit()
    return RedirectResponse("/crm/opps", status_code=303)


# 영업 캘린더

def _month_days(cur):
    # 업무용 월요일 시작. 월 전체가 포함되도록 앞뒤 주 단위로 확장
    first = cur.replace(day=1)
    start = first - timedelta(days=first.weekday())
    last = cur.replace(day=cal_mod.monthrange(cur.year, cur.month)[1])
    end = last + timedelta(days=6 - last.weekday())
    days, d = [], start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def _cal_events(conn, where, args, start, end, today):
    acts = conn.execute(f"""
        SELECT a.id, a.act_date AS d, a.kind, a.subject, COALESCE(p.name, l.name) AS cust_name
        FROM crm_activities a
        LEFT JOIN partners p ON p.id=a.partner_id
        LEFT JOIN crm_leads l ON l.id=a.lead_id
        WHERE {' AND '.join(where)} AND a.act_date BETWEEN ? AND ?
        ORDER BY a.id""", (*args, start, end)).fetchall()
    nexts = conn.execute(f"""
        SELECT a.id, a.next_date AS d, a.next_action, a.subject, COALESCE(p.name, l.name) AS cust_name
        FROM crm_activities a
        LEFT JOIN partners p ON p.id=a.partner_id
        LEFT JOIN crm_leads l ON l.id=a.lead_id
        WHERE {' AND '.join(where)} AND a.next_done=0 AND a.next_date BETWEEN ? AND ?
        ORDER BY a.id""", (*args, start, end)).fetchall()
    by_day = {}
    for a in acts:
        by_day.setdefault(a["d"], []).append({
            "id": a["id"], "cls": "cal-ev-act", "label": ACT_KINDS.get(a["kind"], a["kind"]),
            "subject": a["subject"], "cust_name": a["cust_name"] or "",
        })
    for n in nexts:
        by_day.setdefault(n["d"], []).append({
            "id": n["id"], "cls": "cal-ev-next" + (" cal-ev-overdue" if n["d"] < today else ""),
            "label": n["next_action"] or "할 일", "subject": n["subject"], "cust_name": n["cust_name"] or "",
        })
    return by_day


@router.get("/crm/calendar", response_class=HTMLResponse)
async def crm_calendar(request: Request, view: str = "month", d: str = "", rep: int = 0,
                       u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    today = today_kst().isoformat()
    try:
        cur = date.fromisoformat(d) if d else date.fromisoformat(today)
    except ValueError:
        cur = date.fromisoformat(today)
    rep = _rep(conn, book, rep) or 0
    where, args = ["a.company_id=?"], [book]
    if rep:
        where.append("a.rep_id=?")
        args.append(rep)

    if view == "week":
        start = cur - timedelta(days=cur.weekday())
        end = start + timedelta(days=6)
        prev_d, next_d = (start - timedelta(days=7)).isoformat(), (start + timedelta(days=7)).isoformat()
        by_day = _cal_events(conn, where, args, start.isoformat(), end.isoformat(), today)
        day_info = [(start + timedelta(days=i), False) for i in range(7)]
        title = f"{start.month}월 {start.day}일 ~ {end.month}월 {end.day}일"
    else:
        view = "month"
        days = _month_days(cur)
        by_day = _cal_events(conn, where, args, days[0].isoformat(), days[-1].isoformat(), today)
        day_info = [(day, day.month != cur.month) for day in days]
        prev_d = (cur.replace(day=1) - timedelta(days=1)).isoformat()
        next_d = (cur.replace(day=cal_mod.monthrange(cur.year, cur.month)[1]) + timedelta(days=1)).isoformat()
        title = f"{cur.year}년 {cur.month}월"

    weeks = [day_info[i:i + 7] for i in range(0, len(day_info), 7)]
    grid = [[{"date": day, "iso": day.isoformat(), "other": other, "events": by_day.get(day.isoformat(), [])}
             for day, other in week] for week in weeks]

    return templates.TemplateResponse(request=request, name="erp/crm_calendar.html", context={
        "request": request, "page_title": "영업 캘린더",
        "user_name": u["name"],
        "view": view, "d": cur.isoformat(), "rep": rep, "reps": book_users(conn, book),
        "grid": grid, "today": today, "title": title, "prev_d": prev_d, "next_d": next_d,
        "dow": ["월", "화", "수", "목", "금", "토", "일"],
    })


# 영업 통계

@router.get("/crm/stats", response_class=HTMLResponse)
async def crm_stats(request: Request, date_from: str = "", date_to: str = "",
                    u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    year = today_kst().year
    date_from = date_from or f"{year}-01-01"
    date_to = date_to or f"{year}-12-31"

    leads = conn.execute(
        """SELECT COALESCE(NULLIF(source,''),'미입력') AS source, COUNT(*) AS cnt,
                  SUM(CASE WHEN status='converted' THEN 1 ELSE 0 END) AS converted,
                  SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) AS lost
           FROM crm_leads WHERE company_id=? AND date(created_at)>=? AND date(created_at)<=?
           GROUP BY source ORDER BY cnt DESC""", (book, date_from, date_to)).fetchall()
    lead_rows = []
    for r in leads:
        rate = round(r["converted"] * 100 / r["cnt"], 1) if r["cnt"] else 0
        lead_rows.append({**dict(r), "rate": rate})
    lead_total = {
        "cnt": sum(r["cnt"] for r in lead_rows), "converted": sum(r["converted"] for r in lead_rows),
        "lost": sum(r["lost"] for r in lead_rows),
    }
    lead_total["rate"] = round(lead_total["converted"] * 100 / lead_total["cnt"], 1) if lead_total["cnt"] else 0

    opps = conn.execute(
        """SELECT COALESCE(ru.id, 0) AS rep_id, COALESCE(ru.name, '미지정') AS rep_name,
                  SUM(CASE WHEN o.stage='won' THEN 1 ELSE 0 END) AS won_cnt,
                  SUM(CASE WHEN o.stage='won' THEN o.amount ELSE 0 END) AS won_amt,
                  SUM(CASE WHEN o.stage='lost' THEN 1 ELSE 0 END) AS lost_cnt
           FROM crm_opps o LEFT JOIN users ru ON ru.id=o.rep_id
           WHERE o.company_id=? AND o.stage IN ('won','lost') AND o.closed_at>=? AND o.closed_at<=?
           GROUP BY rep_id ORDER BY won_amt DESC""", (book, date_from, date_to)).fetchall()
    opp_rows = []
    for r in opps:
        total = r["won_cnt"] + r["lost_cnt"]
        rate = round(r["won_cnt"] * 100 / total, 1) if total else 0
        opp_rows.append({**dict(r), "win_rate": rate})
    opp_total = {
        "won_cnt": sum(r["won_cnt"] for r in opp_rows), "won_amt": sum(r["won_amt"] for r in opp_rows),
        "lost_cnt": sum(r["lost_cnt"] for r in opp_rows),
    }
    tot_cnt = opp_total["won_cnt"] + opp_total["lost_cnt"]
    opp_total["win_rate"] = round(opp_total["won_cnt"] * 100 / tot_cnt, 1) if tot_cnt else 0

    return templates.TemplateResponse(request=request, name="erp/crm_stats.html", context={
        "request": request, "page_title": "영업 통계",
        "user_name": u["name"],
        "date_from": date_from, "date_to": date_to,
        "lead_rows": lead_rows, "lead_total": lead_total,
        "opp_rows": opp_rows, "opp_total": opp_total,
    })
