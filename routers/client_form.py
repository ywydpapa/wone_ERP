import json

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from core.deps import get_db, require_client_hr_with_company, templates

router = APIRouter(prefix="/client")


@router.get("/form-templates", response_class=HTMLResponse)
async def form_template_list(
    request: Request,
    status: str = "",
    q: str = "",
    user=Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    sql = "SELECT * FROM form_templates WHERE company_id = ?"
    params = [user["company_id"]]
    if status:
        sql += " AND is_active = ?"
        params.append(1 if status == "active" else 0)
    if q:
        sql += " AND (name LIKE ? OR category LIKE ?)"
        params.append(f"%{q}%")
        params.append(f"%{q}%")
    sql += " ORDER BY is_active DESC, updated_at DESC"
    rows = conn.execute(sql, params).fetchall()
    tpls = []
    for r in rows:
        t = dict(r)
        t["fields"] = json.loads(t["fields"] or "[]")
        t["field_count"] = len(t["fields"])
        tpls.append(t)
    return templates.TemplateResponse("client/form_template_list.html", {
        "request": request, "user": user, "templates_list": tpls,
        "status_filter": status, "q": q,
    })


@router.get("/form-templates/new", response_class=HTMLResponse)
async def form_template_new(
    request: Request,
    user=Depends(require_client_hr_with_company),
):
    return templates.TemplateResponse("client/form_template_edit.html", {
        "request": request, "user": user, "tpl": None,
    })


@router.get("/form-templates/{tpl_id}/edit", response_class=HTMLResponse)
async def form_template_edit(
    request: Request,
    tpl_id: int,
    user=Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    row = conn.execute(
        "SELECT * FROM form_templates WHERE id = ? AND company_id = ?",
        (tpl_id, user["company_id"]),
    ).fetchone()
    if not row:
        return RedirectResponse("/client/form-templates", 303)
    tpl = dict(row)
    tpl["fields"] = json.loads(tpl["fields"] or "[]")
    return templates.TemplateResponse("client/form_template_edit.html", {
        "request": request, "user": user, "tpl": tpl,
    })


@router.post("/form-templates", response_class=RedirectResponse)
async def form_template_create(
    request: Request,
    user=Depends(require_client_hr_with_company),
    conn=Depends(get_db),
    name: str = Form(...),
    category: str = Form("일반"),
    fields_json: str = Form("[]"),
):
    conn.execute(
        "INSERT INTO form_templates (company_id, name, category, fields) VALUES (?, ?, ?, ?)",
        (user["company_id"], name.strip(), category.strip(), fields_json),
    )
    conn.commit()
    return RedirectResponse("/client/form-templates", 303)


@router.post("/form-templates/{tpl_id}", response_class=RedirectResponse)
async def form_template_update(
    request: Request,
    tpl_id: int,
    user=Depends(require_client_hr_with_company),
    conn=Depends(get_db),
    name: str = Form(...),
    category: str = Form("일반"),
    fields_json: str = Form("[]"),
):
    conn.execute(
        """UPDATE form_templates
           SET name = ?, category = ?, fields = ?, updated_at = datetime('now','localtime')
           WHERE id = ? AND company_id = ?""",
        (name.strip(), category.strip(), fields_json, tpl_id, user["company_id"]),
    )
    conn.commit()
    return RedirectResponse("/client/form-templates", 303)


@router.post("/form-templates/{tpl_id}/toggle", response_class=RedirectResponse)
async def form_template_toggle(
    request: Request,
    tpl_id: int,
    user=Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    conn.execute(
        """UPDATE form_templates
           SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END,
               updated_at = datetime('now','localtime')
           WHERE id = ? AND company_id = ?""",
        (tpl_id, user["company_id"]),
    )
    conn.commit()
    return RedirectResponse("/client/form-templates", 303)


@router.post("/form-templates/{tpl_id}/delete", response_class=RedirectResponse)
async def form_template_delete(
    request: Request,
    tpl_id: int,
    user=Depends(require_client_hr_with_company),
    conn=Depends(get_db),
):
    conn.execute(
        "DELETE FROM form_templates WHERE id = ? AND company_id = ?",
        (tpl_id, user["company_id"]),
    )
    conn.commit()
    return RedirectResponse("/client/form-templates", 303)
