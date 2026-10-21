import json

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from core.deps import get_db, require_staff, templates
from core.erp_export import EXPORT_SCHEMAS, apply_template, std_lines, dummy_rows

router = APIRouter(prefix="/platform")


@router.get("/export-templates", response_class=HTMLResponse)
async def tpl_list(
    request: Request,
    company_id: int = 0,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    companies = [dict(r) for r in conn.execute(
        "SELECT id, name FROM client_companies ORDER BY name").fetchall()]
    tpls = {}
    if company_id:
        tpls = {r["module"]: dict(r) for r in conn.execute(
            "SELECT * FROM export_templates WHERE company_id = ?", (company_id,)).fetchall()}
    return templates.TemplateResponse(
        request=request,
        name="platform/export_templates.html",
        context={
            "user": user, "companies": companies,
            "company_id": company_id, "tpls": tpls, "schemas": EXPORT_SCHEMAS,
        },
    )


@router.get("/export-templates/{company_id}/{module}", response_class=HTMLResponse)
async def tpl_edit(
    company_id: int,
    module: str,
    request: Request,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    if module not in EXPORT_SCHEMAS:
        return RedirectResponse("/platform/export-templates", status_code=303)
    company = conn.execute("SELECT id, name FROM client_companies WHERE id = ?",
                           (company_id,)).fetchone()
    if not company:
        return RedirectResponse("/platform/export-templates", status_code=303)
    tpl = conn.execute(
        "SELECT * FROM export_templates WHERE company_id = ? AND module = ?",
        (company_id, module)).fetchone()
    schema = EXPORT_SCHEMAS[module]
    saved = {c["src"]: c for c in json.loads(tpl["columns"])} if tpl else {}
    order = {c["src"]: i for i, c in enumerate(json.loads(tpl["columns"]), 1)} if tpl else {}
    rows = dummy_rows(module)
    if tpl:
        pv_headers, pv_lines = apply_template(module, tpl, rows)
    else:
        pv_headers, pv_lines = std_lines(module, rows)
    return templates.TemplateResponse(
        request=request,
        name="platform/export_template_edit.html",
        context={
            "user": user, "company": dict(company), "module": module,
            "schema": schema, "tpl": dict(tpl) if tpl else None, "saved": saved, "order": order,
            "pv_headers": pv_headers, "pv_lines": pv_lines,
        },
    )


@router.post("/export-templates/{company_id}/{module}")
async def tpl_save(
    company_id: int,
    module: str,
    request: Request,
    file_format: str = Form("xlsx"),
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    if module not in EXPORT_SCHEMAS:
        return JSONResponse({"error": "유효하지 않은 모듈입니다."}, status_code=400)
    if file_format not in ("csv", "xlsx"):
        return JSONResponse({"error": "파일 포맷을 확인해 주세요."}, status_code=400)
    form = await request.form()
    cols = []
    for src, _ in EXPORT_SCHEMAS[module]["columns"]:
        if not form.get(f"use_{src}"):
            continue
        raw_ord = form.get(f"ord_{src}") or ""
        ord_val = int(raw_ord) if raw_ord.strip().lstrip("-").isdigit() else 999
        raw_fmt = form.get(f"fmt_{src}") or ""
        cols.append({
            "src": src,
            "header": (form.get(f"header_{src}") or "").strip(),
            "fmt": raw_fmt if raw_fmt in ("", "ymd", "comma") else "",
            "ord": ord_val,
        })
    cols.sort(key=lambda c: c["ord"])
    for c in cols:
        del c["ord"]
    conn.execute(
        "INSERT INTO export_templates (company_id, module, columns, file_format, created_by) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(company_id, module) DO UPDATE SET "
        "columns = excluded.columns, file_format = excluded.file_format, "
        "updated_at = datetime('now','localtime')",
        (company_id, module, json.dumps(cols, ensure_ascii=False), file_format, user["id"]))
    conn.commit()
    return RedirectResponse(f"/platform/export-templates/{company_id}/{module}", status_code=303)


@router.get("/export-logs", response_class=HTMLResponse)
async def export_log_list(
    request: Request,
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    logs = [dict(r) for r in conn.execute(
        "SELECT e.*, c.name AS company_name, u.name AS user_name, wr.title AS request_title "
        "FROM export_logs e "
        "JOIN client_companies c ON c.id = e.company_id "
        "JOIN users u ON u.id = e.user_id "
        "JOIN work_requests wr ON wr.id = e.work_request_id "
        "ORDER BY e.created_at DESC LIMIT 200").fetchall()]
    return templates.TemplateResponse(
        request=request,
        name="platform/export_logs.html",
        context={"user": user, "logs": logs},
    )
