from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse

from core import notes, partner
from core.books import require_book
from core.deps import get_db, templates
from core.export import csv_response
from core.tz import today_kst
from routers._helpers import to_int

router = APIRouter()

PER_PAGE = 30
NOTE_SORTS = {"no": "note_no", "partner": "p.name", "amount": "amount", "issue": "issue_date",
              "due": "due_date", "status": "status"}
DUE_SOON_DAYS = 7
NOTE_STATUS_CLASS = {
    "held": "status-wait", "issued": "status-wait",
    "dishonored": "status-reject", "canceled": "status-reject",
    "collected": "status-done", "discounted": "status-done",
    "endorsed": "status-done", "paid": "status-done",
}


def _partners(conn, book):
    return conn.execute(
        f"SELECT id, name FROM partners WHERE company_id=? AND is_active=1 AND {partner.NOT_FINANCE} ORDER BY name",
        (book,)).fetchall()


def _bank_accounts(conn, book):
    return conn.execute(
        "SELECT id, bank, account_no, name FROM bank_accounts WHERE company_id=? AND is_active=1 "
        "ORDER BY bank, account_no", (book,)).fetchall()


@router.get("/notes", response_class=HTMLResponse)
async def note_list(request: Request, u: dict = Depends(require_book), conn=Depends(get_db),
                    sort: str = "", dir: str = "", export: str = ""):
    book = u["book"]
    qp = request.query_params
    kind = qp.get("kind") if qp.get("kind") in ("recv", "pay") else "recv"
    status = qp.get("status", "")
    partner_id = qp.get("partner_id", "")
    due_from = qp.get("due_from", "")
    due_to = qp.get("due_to", "")
    page = qp.get("page", "1")
    page = int(page) if page.isdigit() else 1

    where = ["n.company_id=?", "n.kind=?"]
    params = [book, kind]
    if status in notes.STATUS[kind]:
        where.append("n.status=?")
        params.append(status)
    if partner_id.isdigit():
        where.append("n.partner_id=?")
        params.append(int(partner_id))
    if due_from:
        where.append("n.due_date>=?")
        params.append(due_from)
    if due_to:
        where.append("n.due_date<=?")
        params.append(due_to)
    where_sql = " AND ".join(where)

    order = NOTE_SORTS.get(sort)
    order_sql = f"ORDER BY {order} {'DESC' if dir == 'desc' else 'ASC'}, n.id DESC" if order \
        else "ORDER BY n.due_date ASC, n.id DESC"

    base_sql = f"""SELECT n.*, p.name AS partner_name FROM notes n
                   JOIN partners p ON p.id=n.partner_id WHERE {where_sql} {order_sql}"""

    if export == "csv":
        rows = conn.execute(base_sql, params).fetchall()
        csv_rows = [[r["note_no"], r["partner_name"], r["amount"], r["issue_date"], r["due_date"],
                     r["bank"] or "", "전자" if r["is_electronic"] else "일반",
                     notes.STATUS[kind].get(r["status"], r["status"])] for r in rows]
        return csv_response(["어음번호", "거래처", "금액", "발행일", "만기일", "지급장소", "구분", "상태"],
                            csv_rows, "notes.csv")

    total = conn.execute(f"SELECT COUNT(*) FROM notes n JOIN partners p ON p.id=n.partner_id WHERE {where_sql}",
                         params).fetchone()[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    rows = [dict(r) for r in conn.execute(
        f"{base_sql} LIMIT ? OFFSET ?", params + [PER_PAGE, (page - 1) * PER_PAGE]).fetchall()]

    today = today_kst().isoformat()
    soon = (today_kst() + timedelta(days=DUE_SOON_DAYS)).isoformat()
    for r in rows:
        r["due_soon"] = today <= r["due_date"] <= soon and r["status"] in ("held", "issued")
        r["status_class"] = NOTE_STATUS_CLASS.get(r["status"], "")
        r["status_label"] = notes.STATUS[kind].get(r["status"], r["status"])

    return templates.TemplateResponse(request=request, name="erp/note_list.html", context={
        "request": request, "page_title": "어음 관리", "user_name": u["name"],
        "rows": rows, "kind": kind, "status": status, "partner_id": partner_id,
        "due_from": due_from, "due_to": due_to, "partners": _partners(conn, book),
        "statuses": notes.STATUS[kind], "today": today, "soon": soon,
        "page": page, "total_pages": total_pages, "total_count": total,
        "base_url": f"/notes?kind={kind}&status={status}&partner_id={partner_id}"
                    f"&due_from={due_from}&due_to={due_to}&sort={sort}&dir={dir}",
        "sort": sort, "dir": dir,
    })


@router.get("/notes/new", response_class=HTMLResponse)
async def note_new(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    kind = request.query_params.get("kind") if request.query_params.get("kind") in ("recv", "pay") else "recv"
    return templates.TemplateResponse(request=request, name="erp/note_form.html", context={
        "request": request, "page_title": "어음 등록", "user_name": u["name"],
        "kind": kind, "partners": _partners(conn, u["book"]),
    })


@router.post("/notes")
async def note_create(request: Request, u: dict = Depends(require_book), conn=Depends(get_db)):
    book, uid = u["book"], u["id"]
    form = await request.form()
    kind = form.get("kind", "")
    if kind not in ("recv", "pay"):
        return JSONResponse({"error": "구분을 선택해 주세요."}, status_code=400)
    try:
        pid = to_int(form.get("partner_id", ""))
        amount = to_int(form.get("amount"))
    except ValueError:
        return JSONResponse({"error": "입력 값을 확인해 주세요."}, status_code=400)
    note_no = form.get("note_no", "").strip()
    if not note_no:
        return JSONResponse({"error": "어음번호를 입력해 주세요."}, status_code=400)
    for d in (form.get("issue_date", ""), form.get("due_date", "")):
        try:
            date.fromisoformat(d)
        except ValueError:
            return JSONResponse({"error": "일자를 확인해 주세요."}, status_code=400)

    f = {"partner_id": pid, "amount": amount, "note_no": note_no,
         "issue_date": form.get("issue_date"), "due_date": form.get("due_date"),
         "bank": form.get("bank", "").strip(), "is_electronic": form.get("is_electronic") == "1",
         "memo": form.get("memo", "").strip()}
    try:
        nid = notes.issue(conn, book, uid, f) if kind == "pay" else notes.receive(conn, book, uid, f)
    except LookupError:
        return JSONResponse({"error": "거래처를 찾을 수 없습니다."}, status_code=404)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return RedirectResponse(f"/notes/{nid}", status_code=303)


def _note_detail(conn, book, note_id):
    n = conn.execute(
        """SELECT n.*, p.name AS partner_name, e.name AS endorsee_name, cu.name AS created_name,
                  id_.slip_no AS issue_slip_no, cd.slip_no AS close_slip_no
           FROM notes n
           JOIN partners p ON p.id=n.partner_id
           LEFT JOIN partners e ON e.id=n.endorsee_id
           LEFT JOIN users cu ON cu.id=n.created_by
           LEFT JOIN erp_docs id_ ON id_.id=n.issue_doc_id
           LEFT JOIN erp_docs cd ON cd.id=n.close_doc_id
           WHERE n.id=? AND n.company_id=?""",
        (note_id, book),
    ).fetchone()
    return n


@router.get("/notes/{note_id}", response_class=HTMLResponse)
async def note_detail(request: Request, note_id: int, u: dict = Depends(require_book), conn=Depends(get_db)):
    book = u["book"]
    n = _note_detail(conn, book, note_id)
    if not n:
        return HTMLResponse("<h2>어음을 찾을 수 없습니다</h2>", status_code=404)
    return templates.TemplateResponse(request=request, name="erp/note_detail.html", context={
        "request": request, "page_title": "어음 상세", "user_name": u["name"],
        "n": n, "status_label": notes.STATUS[n["kind"]].get(n["status"], n["status"]),
        "status_class": NOTE_STATUS_CLASS.get(n["status"], ""),
        "partners": _partners(conn, book), "bank_accounts": _bank_accounts(conn, book),
        "can_edit": partner.can_edit(u),
    })


def _act(request_date):
    try:
        date.fromisoformat(request_date)
    except ValueError:
        raise ValueError("일자를 확인해 주세요.")
    return request_date


@router.post("/notes/{note_id}/collect")
async def note_collect(request: Request, note_id: int, u: dict = Depends(partner.require_editor),
                       conn=Depends(get_db)):
    form = await request.form()
    try:
        action_date = _act(form.get("action_date", ""))
        bank_account_id = to_int(form.get("bank_account_id", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e) or "입력 값을 확인해 주세요."}, status_code=400)
    try:
        notes.collect(conn, u["book"], u["id"], note_id, action_date, bank_account_id)
    except LookupError:
        return JSONResponse({"error": "어음을 찾을 수 없습니다."}, status_code=404)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return JSONResponse({"ok": True})


@router.post("/notes/{note_id}/discount")
async def note_discount(request: Request, note_id: int, u: dict = Depends(partner.require_editor),
                        conn=Depends(get_db)):
    form = await request.form()
    try:
        action_date = _act(form.get("action_date", ""))
        bank_account_id = to_int(form.get("bank_account_id", ""))
        fee = to_int(form.get("fee", "0") or "0")
    except ValueError as e:
        return JSONResponse({"error": str(e) or "입력 값을 확인해 주세요."}, status_code=400)
    try:
        notes.discount(conn, u["book"], u["id"], note_id, action_date, bank_account_id, fee)
    except LookupError:
        return JSONResponse({"error": "어음을 찾을 수 없습니다."}, status_code=404)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return JSONResponse({"ok": True})


@router.post("/notes/{note_id}/endorse")
async def note_endorse(request: Request, note_id: int, u: dict = Depends(partner.require_editor),
                       conn=Depends(get_db)):
    form = await request.form()
    try:
        action_date = _act(form.get("action_date", ""))
        endorsee_id = to_int(form.get("endorsee_id", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e) or "입력 값을 확인해 주세요."}, status_code=400)
    try:
        notes.endorse(conn, u["book"], u["id"], note_id, action_date, endorsee_id)
    except LookupError:
        return JSONResponse({"error": "거래처 또는 어음을 찾을 수 없습니다."}, status_code=404)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return JSONResponse({"ok": True})


@router.post("/notes/{note_id}/dishonor")
async def note_dishonor(request: Request, note_id: int, u: dict = Depends(partner.require_editor),
                        conn=Depends(get_db)):
    form = await request.form()
    try:
        action_date = _act(form.get("action_date", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    try:
        notes.dishonor(conn, u["book"], u["id"], note_id, action_date)
    except LookupError:
        return JSONResponse({"error": "어음을 찾을 수 없습니다."}, status_code=404)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return JSONResponse({"ok": True})


@router.post("/notes/{note_id}/pay")
async def note_pay(request: Request, note_id: int, u: dict = Depends(partner.require_editor),
                   conn=Depends(get_db)):
    form = await request.form()
    try:
        action_date = _act(form.get("action_date", ""))
        bank_account_id = to_int(form.get("bank_account_id", ""))
    except ValueError as e:
        return JSONResponse({"error": str(e) or "입력 값을 확인해 주세요."}, status_code=400)
    try:
        notes.pay(conn, u["book"], u["id"], note_id, action_date, bank_account_id)
    except LookupError:
        return JSONResponse({"error": "어음을 찾을 수 없습니다."}, status_code=404)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return JSONResponse({"ok": True})


@router.post("/notes/{note_id}/cancel")
async def note_cancel(request: Request, note_id: int, u: dict = Depends(partner.require_editor),
                      conn=Depends(get_db)):
    form = await request.form()
    rev_date = form.get("rev_date", "").strip()
    if rev_date:
        try:
            date.fromisoformat(rev_date)
        except ValueError:
            return JSONResponse({"error": "일자를 확인해 주세요."}, status_code=400)
    try:
        notes.cancel(conn, u["book"], u["id"], note_id, rev_date or None)
    except LookupError:
        return JSONResponse({"error": "어음을 찾을 수 없습니다."}, status_code=404)
    except ValueError as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    conn.commit()
    return JSONResponse({"ok": True})
