from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from core.tz import now_kst
from core.deps import get_db, templates
from core.books import emp_book, book_label, require_hr_book
from core import audit

router = APIRouter()

# 장애인고용촉진법 제5조의2. 전 사업주 연 1회 이상 실시
METHODS = ("집체교육", "온라인교육", "현장교육(사업장 방문)", "자체교육")


def training_stats(conn, book, year):
    first_day = f"{year}-01-01"
    last_day = f"{year}-12-31"
    cbook = emp_book(book)

    targets = [dict(e) for e in conn.execute(
        """SELECT id, name, employee_no FROM employees
           WHERE company_id IS ? AND (hire_date IS NULL OR hire_date <= ?)
             AND (resign_date IS NULL OR resign_date >= ?)
           ORDER BY employee_no, name""",
        (cbook, last_day, first_day),
    ).fetchall()]

    completed_ids = {r["employee_id"] for r in conn.execute(
        """SELECT DISTINCT a.employee_id FROM disability_awareness_attendees a
           JOIN disability_awareness_trainings t ON t.id = a.training_id
           WHERE t.company_id IS ? AND a.completed=1 AND t.held_date BETWEEN ? AND ?""",
        (cbook, first_day, last_day),
    ).fetchall()}

    for e in targets:
        e["completed"] = e["id"] in completed_ids

    total = len(targets)
    completed_cnt = sum(1 for e in targets if e["completed"])
    rate = round(completed_cnt / total * 100, 1) if total else 0.0
    return {
        "total": total, "completed_cnt": completed_cnt, "rate": rate,
        "missed": [e for e in targets if not e["completed"]],
    }


@router.get("/hr/disability-training", response_class=HTMLResponse)
async def training_list(
    request: Request,
    year: int = 0,
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    year = year or now_kst().year
    book = user["book"]
    cbook = emp_book(book)

    sessions = [dict(s) for s in conn.execute(
        """SELECT t.*, COUNT(a.id) AS attendee_cnt FROM disability_awareness_trainings t
           LEFT JOIN disability_awareness_attendees a ON a.training_id = t.id AND a.completed=1
           WHERE t.company_id IS ? AND t.held_date BETWEEN ? AND ?
           GROUP BY t.id ORDER BY t.held_date DESC""",
        (cbook, f"{year}-01-01", f"{year}-12-31"),
    ).fetchall()]

    employees = conn.execute(
        "SELECT id, name, employee_no FROM employees WHERE company_id IS ? AND status='active' ORDER BY employee_no, name",
        (cbook,),
    ).fetchall()

    return templates.TemplateResponse(
        request=request, name="hr/training_list.html", context={
            "request": request,
            "page_title": "장애인 인식개선교육 관리",
            "user_name": user["name"],
            "user_role": user["role"],
            "book_name": book_label(conn, book),
            "year": year,
            "sessions": sessions,
            "employees": employees,
            "methods": METHODS,
            "stats": training_stats(conn, book, year),
        }
    )


@router.post("/hr/disability-training")
async def training_create(
    request: Request,
    held_date: str = Form(...),
    method: str = Form(...),
    instructor: str = Form(""),
    content: str = Form(""),
    user: dict = Depends(require_hr_book),
    conn=Depends(get_db),
):
    book = user["book"]
    cbook = emp_book(book)
    form = await request.form()
    raw_ids = [int(v) for v in form.getlist("attendee_id") if v.isdigit()]

    valid_ids = []
    if raw_ids:
        marks = ",".join("?" * len(raw_ids))
        valid_ids = [r["id"] for r in conn.execute(
            f"SELECT id FROM employees WHERE company_id IS ? AND id IN ({marks})",
            (cbook, *raw_ids),
        ).fetchall()]

    cur = conn.execute(
        """INSERT INTO disability_awareness_trainings
           (company_id, held_date, method, instructor, content, created_by)
           VALUES (?,?,?,?,?,?)""",
        (cbook, held_date, method, instructor, content, user["id"]),
    )
    training_id = cur.lastrowid
    for emp_id in valid_ids:
        conn.execute(
            "INSERT INTO disability_awareness_attendees (training_id, employee_id, completed) VALUES (?,?,1)",
            (training_id, emp_id),
        )
    audit.log(conn, user["id"], "training_create", "disability_awareness_training", training_id,
              f"{held_date} {method} 교육 {len(valid_ids)}명 이수", company_id=book)
    conn.commit()

    return RedirectResponse(url=f"/hr/disability-training?year={held_date[:4]}", status_code=303)
