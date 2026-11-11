import json
from itertools import zip_longest
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from core.deps import get_db, require_staff, templates
from core.erp_export import EXPORT_SCHEMAS, PRESETS, apply_preset, apply_template, std_lines, dummy_rows

router = APIRouter(prefix="/platform")


def clean_name(raw):
    name = (raw or "").strip()[:20]
    return name or "기본"


@router.get("/export-templates", response_class=HTMLResponse)
async def tpl_list(
    request: Request,
    company_id: int = 0,
    name: str = "",
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    companies = [dict(r) for r in conn.execute(
        "SELECT id, name FROM client_companies ORDER BY name").fetchall()]
    names, tpls = [], {}
    if company_id:
        names = [r["name"] for r in conn.execute(
            "SELECT DISTINCT name FROM export_templates WHERE company_id = ? ORDER BY name",
            (company_id,)).fetchall()]
        name = clean_name(name or (names[0] if names else ""))
        if name not in names:
            names.append(name)
        tpls = {r["module"]: dict(r) for r in conn.execute(
            "SELECT * FROM export_templates WHERE company_id = ? AND name = ?",
            (company_id, name)).fetchall()}
    return templates.TemplateResponse(
        request=request,
        name="platform/export_templates.html",
        context={
            "user": user, "companies": companies, "company_id": company_id,
            "names": names, "cur_name": name, "tpls": tpls, "schemas": EXPORT_SCHEMAS,
            "presets": PRESETS,
        },
    )


@router.post("/export-templates/{company_id}/preset")
async def tpl_preset(
    company_id: int,
    preset: str = Form(...),
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    p = PRESETS.get(preset)
    company = conn.execute("SELECT id FROM client_companies WHERE id = ?", (company_id,)).fetchone()
    if not p or not company:
        return RedirectResponse("/platform/export-templates", status_code=303)
    apply_preset(conn, company_id, preset, {}, user["id"])
    conn.commit()
    return RedirectResponse(
        f"/platform/export-templates?company_id={company_id}&name={quote(p['name'])}", status_code=303)


@router.get("/export-templates/{company_id}/{module}", response_class=HTMLResponse)
async def tpl_edit(
    company_id: int,
    module: str,
    request: Request,
    name: str = "",
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    if module not in EXPORT_SCHEMAS:
        return RedirectResponse("/platform/export-templates", status_code=303)
    company = conn.execute("SELECT id, name FROM client_companies WHERE id = ?",
                           (company_id,)).fetchone()
    if not company:
        return RedirectResponse("/platform/export-templates", status_code=303)
    name = clean_name(name)
    tpl = conn.execute(
        "SELECT * FROM export_templates WHERE company_id = ? AND module = ? AND name = ?",
        (company_id, module, name)).fetchone()
    schema = EXPORT_SCHEMAS[module]
    cols = json.loads(tpl["columns"]) if tpl else []
    saved = {c["src"]: c for c in cols if c["src"] != "_fixed"}
    order = {c["src"]: i for i, c in enumerate(cols, 1) if c["src"] != "_fixed"}
    fixed = [dict(c, ord=i) for i, c in enumerate(cols, 1) if c["src"] == "_fixed"] + [{}, {}]
    rows = dummy_rows(module)
    if tpl:
        pv_headers, pv_lines = apply_template(module, tpl, rows)
    else:
        pv_headers, pv_lines = std_lines(module, rows)
    return templates.TemplateResponse(
        request=request,
        name="platform/export_template_edit.html",
        context={
            "user": user, "company": dict(company), "module": module, "name": name,
            "schema": schema, "all_cols": schema["columns"] + schema.get("derived", []),
            "tpl": dict(tpl) if tpl else None, "saved": saved, "order": order, "fixed": fixed,
            "pv_headers": pv_headers, "pv_lines": pv_lines,
        },
    )


@router.post("/export-templates/{company_id}/{module}")
async def tpl_save(
    company_id: int,
    module: str,
    request: Request,
    name: str = Form("기본"),
    file_format: str = Form("xlsx"),
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    if module not in EXPORT_SCHEMAS:
        return JSONResponse({"error": "유효하지 않은 모듈입니다."}, status_code=400)
    if file_format not in ("csv", "xlsx"):
        return JSONResponse({"error": "파일 포맷을 확인해 주세요."}, status_code=400)
    name = clean_name(name)
    form = await request.form()
    schema = EXPORT_SCHEMAS[module]

    cols = []
    for src, _ in schema["columns"] + schema.get("derived", []):
        if not form.get(f"use_{src}"):
            continue
        raw_fmt = form.get(f"fmt_{src}") or ""
        raw_ord = (form.get(f"ord_{src}") or "").strip()
        c = {
            "src": src,
            "header": (form.get(f"header_{src}") or "").strip(),
            "fmt": raw_fmt if raw_fmt in ("", "ymd", "comma", "acct5") else "",
            "ord": int(raw_ord) if raw_ord.lstrip("-").isdigit() else 999,
        }
        if src == "dc_type":
            codes = [v.strip() for v in (form.get("codes_dc_type") or "").split(",")]
            c["codes"] = codes if len(codes) == 2 and all(codes) else ["차변", "대변"]
        cols.append(c)
    for header, value, raw_ord, inp, card in zip_longest(form.getlist("fix_header"), form.getlist("fix_value"),
                                                         form.getlist("fix_ord"), form.getlist("fix_input"),
                                                         form.getlist("fix_card"), fillvalue=""):
        if header.strip():
            raw_ord = raw_ord.strip()
            c = {"src": "_fixed", "header": header.strip(), "value": value.strip(),
                 "ord": int(raw_ord) if raw_ord.lstrip("-").isdigit() else 999}
            if inp:
                c["input"] = inp
            if card:
                c["card"] = True
            cols.append(c)
    cols.sort(key=lambda c: c["ord"])
    for c in cols:
        del c["ord"]
    conn.execute(
        "INSERT INTO export_templates (company_id, module, name, columns, file_format, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(company_id, module, name) DO UPDATE SET "
        "columns = excluded.columns, file_format = excluded.file_format, "
        "updated_at = datetime('now','localtime')",
        (company_id, module, name, json.dumps(cols, ensure_ascii=False), file_format, user["id"]))
    conn.commit()
    return RedirectResponse(
        f"/platform/export-templates/{company_id}/{module}?name={quote(name)}", status_code=303)


@router.post("/export-templates/{company_id}/{module}/delete")
async def tpl_delete(
    company_id: int,
    module: str,
    name: str = Form(...),
    user: dict = Depends(require_staff),
    conn=Depends(get_db),
):
    conn.execute("DELETE FROM export_templates WHERE company_id = ? AND module = ? AND name = ?",
                 (company_id, module, name))
    conn.commit()
    return RedirectResponse(
        f"/platform/export-templates?company_id={company_id}&name={quote(name)}", status_code=303)


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
