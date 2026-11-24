import json
from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from core.deps import get_db, require_login, templates

router = APIRouter()


def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cardnews_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '새 카드뉴스',
            aspect_ratio TEXT NOT NULL DEFAULT '1:1',
            width INTEGER NOT NULL DEFAULT 1080,
            height INTEGER NOT NULL DEFAULT 1080,
            slides_json TEXT NOT NULL DEFAULT '[]',
            thumbnail TEXT DEFAULT '',
            created_by INTEGER,
            created_by_name TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()


@router.get("/cardnews", response_class=HTMLResponse)
async def cardnews_list(request: Request, q: str = "", u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    query = "SELECT * FROM cardnews_projects"
    params = []
    if q:
        query += " WHERE title LIKE '%' || ? || '%'"
        params.append(q)
    query += " ORDER BY updated_at DESC, id DESC"

    rows = conn.execute(query, params).fetchall()
    projects = [dict(r) for r in rows]

    return templates.TemplateResponse(
        request=request,
        name="cardnews/list.html",
        context={
            "request": request,
            "page_title": "카드뉴스 제작 관리",
            "user_name": u.get("name", ""),
            "projects": projects,
            "q": q,
        }
    )


@router.get("/cardnews/editor", response_class=HTMLResponse)
async def cardnews_editor(request: Request, id: int = 0, u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    project = None
    if id > 0:
        row = conn.execute("SELECT * FROM cardnews_projects WHERE id = ?", (id,)).fetchone()
        if row:
            project = dict(row)

    return templates.TemplateResponse(
        request=request,
        name="cardnews/editor.html",
        context={
            "request": request,
            "page_title": "카드뉴스 편집기",
            "user_name": u.get("name", ""),
            "project": project,
            "project_id": id if project else 0,
        }
    )


@router.get("/cardnews/api/{project_id}")
async def get_project(project_id: int, u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    row = conn.execute("SELECT * FROM cardnews_projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    return JSONResponse(dict(row))


@router.post("/cardnews/api/save")
async def save_project(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="유효하지 않은 요청 데이터입니다.")

    project_id = int(data.get("id") or 0)
    title = (data.get("title") or "새 카드뉴스").strip()
    aspect_ratio = data.get("aspect_ratio") or "1:1"
    width = int(data.get("width") or 1080)
    height = int(data.get("height") or 1080)
    slides_json = data.get("slides_json")
    if isinstance(slides_json, (list, dict)):
        slides_json = json.dumps(slides_json, ensure_ascii=False)
    elif not slides_json:
        slides_json = "[]"

    thumbnail = data.get("thumbnail") or ""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_id = u.get("id")
    user_name = u.get("name", "")

    if project_id > 0:
        # 기존 수정
        conn.execute("""
            UPDATE cardnews_projects
            SET title = ?, aspect_ratio = ?, width = ?, height = ?, slides_json = ?, thumbnail = ?, updated_at = ?
            WHERE id = ?
        """, (title, aspect_ratio, width, height, slides_json, thumbnail, now_str, project_id))
        conn.commit()
        return JSONResponse({"ok": True, "id": project_id, "message": "저장되었습니다."})
    else:
        # 신규 생성
        cur = conn.execute("""
            INSERT INTO cardnews_projects (title, aspect_ratio, width, height, slides_json, thumbnail, created_by, created_by_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, aspect_ratio, width, height, slides_json, thumbnail, user_id, user_name, now_str, now_str))
        conn.commit()
        new_id = cur.lastrowid
        return JSONResponse({"ok": True, "id": new_id, "message": "성공적으로 생성되었습니다."})


@router.post("/cardnews/api/{project_id}/delete")
async def delete_project(project_id: int, u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    conn.execute("DELETE FROM cardnews_projects WHERE id = ?", (project_id,))
    conn.commit()
    return JSONResponse({"ok": True, "message": "삭제되었습니다."})
