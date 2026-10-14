import pathlib
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from core import audit, backup
from core import db as core_db
from core.deps import get_db, require_login, templates

router = APIRouter()

# DB 파일 전체가 전 고객사 데이터라 platform_staff만 허용
BACKUP_DIR = pathlib.Path(core_db.DB_PATH).parent / "var" / "backups"
BACKUP_NAME_RE = re.compile(r"^erp-\d{8}-\d{4}(-\d{2})?\.db$")


def require_backup(request: Request):
    u = require_login(request)
    if u["role"] != "platform_staff":
        raise HTTPException(status_code=403)
    return u


@router.get("/settings/backup", response_class=HTMLResponse)
async def backup_list(request: Request, u: dict = Depends(require_backup)):
    rows = backup.files(BACKUP_DIR)
    for r in rows:
        mb = r["size"] / 1024 / 1024
        r["size_label"] = f"{mb:.1f}MB" if mb >= 1 else f"{r['size'] / 1024:.1f}KB"
    return templates.TemplateResponse(request=request, name="settings/backup.html", context={
        "request": request, "page_title": "DB 백업", "user_name": u["name"], "files": rows,
    })


@router.post("/settings/backup")
async def backup_create(u: dict = Depends(require_backup), conn=Depends(get_db)):
    path = backup.run(core_db.DB_PATH, BACKUP_DIR)
    audit.log(conn, u["id"], "backup", "backup", None, pathlib.Path(path).name)
    conn.commit()
    return RedirectResponse("/settings/backup", status_code=303)


@router.get("/settings/backup/{name}")
async def backup_download(name: str, u: dict = Depends(require_backup)):
    if not BACKUP_NAME_RE.match(name):
        raise HTTPException(status_code=404)
    path = pathlib.Path(BACKUP_DIR) / name
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, filename=name)
