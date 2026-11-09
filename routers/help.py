from itertools import groupby

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from core.deps import require_login, templates
from core.help import GROUPS

router = APIRouter()


def _toc():
    toc = []
    for g in GROUPS:
        pages = [dict(p, path=path, anchor=f"m-{g['id']}-{i}") for i, (path, p) in enumerate(g["pages"].items(), 1)]
        toc.append({
            "id": g["id"], "group": g["group"], "flow": g.get("flow", []),
            "sections": [{"name": k, "pages": list(v)} for k, v in groupby(pages, key=lambda p: p["section"])],
        })
    return toc


TOC = _toc()


@router.get("/manual", response_class=HTMLResponse)
async def manual(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(request=request, name="manual.html", context={
        "request": request, "page_title": "사용 매뉴얼", "user_name": u["name"], "groups": TOC,
    })
