import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from core.deps import get_db, require_login, templates

router = APIRouter()

BANNER_PRESETS = [
    {
        "id": "web_banner",
        "name": "메인 웹 배너",
        "category": "web",
        "width": 1200,
        "height": 400,
        "ratio": "3:1",
        "desc": "홈페이지 메인 및 프로모션용 와이드 배너",
        "icon": "fa-desktop",
    },
    {
        "id": "youtube_thumb",
        "name": "유튜브 썸네일 / 와이드",
        "category": "sns",
        "width": 1280,
        "height": 720,
        "ratio": "16:9",
        "desc": "유튜브 썸네일 및 고화질 와이드 배너",
        "icon": "fa-youtube",
    },
    {
        "id": "sns_landscape",
        "name": "SNS / 포털 배너",
        "category": "sns",
        "width": 1200,
        "height": 630,
        "ratio": "1.91:1",
        "desc": "블로그, 페이스북, 링크 미리보기 배너",
        "icon": "fa-share-nodes",
    },
    {
        "id": "popup_square",
        "name": "팝업 / 정사각형 배너",
        "category": "popup",
        "width": 600,
        "height": 600,
        "ratio": "1:1",
        "desc": "홈페이지 이벤트 팝업 및 인스타그램 배너",
        "icon": "fa-window-maximize",
    },
    {
        "id": "sidebar_tall",
        "name": "세로형 사이드 배너",
        "category": "web",
        "width": 300,
        "height": 600,
        "ratio": "1:2",
        "desc": "홈페이지 우측/좌측 세로형 날개 배너",
        "icon": "fa-columns",
    },
    {
        "id": "mobile_bar",
        "name": "모바일 띠배너",
        "category": "mobile",
        "width": 720,
        "height": 180,
        "ratio": "4:1",
        "desc": "모바일 앱 및 웹페이지 상/하단 띠배너",
        "icon": "fa-mobile-screen",
    },
]


def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS banner_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '새 배너',
            category TEXT NOT NULL DEFAULT 'web',
            preset_name TEXT NOT NULL DEFAULT '가로형 배너 (1200x400)',
            width INTEGER NOT NULL DEFAULT 1200,
            height INTEGER NOT NULL DEFAULT 400,
            canvas_json TEXT NOT NULL DEFAULT '{}',
            thumbnail TEXT DEFAULT '',
            created_by INTEGER,
            created_by_name TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()


@router.get("/banner", response_class=HTMLResponse)
async def banner_list(request: Request, q: str = "", cat: str = "all", u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    query = "SELECT * FROM banner_projects"
    params = []
    conditions = []

    if q:
        conditions.append("title LIKE '%' || ? || '%'")
        params.append(q)
    if cat and cat != "all":
        conditions.append("category = ?")
        params.append(cat)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY updated_at DESC, id DESC"

    rows = conn.execute(query, params).fetchall()
    projects = [dict(r) for r in rows]

    return templates.TemplateResponse(
        request=request,
        name="banner/list.html",
        context={
            "request": request,
            "page_title": "배너 제작 관리",
            "user_name": u.get("name", ""),
            "projects": projects,
            "presets": BANNER_PRESETS,
            "q": q,
            "cat": cat,
        }
    )


@router.get("/banner/editor", response_class=HTMLResponse)
async def banner_editor(request: Request, id: int = 0, preset: str = "web_banner", u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    project = None

    if id > 0:
        row = conn.execute("SELECT * FROM banner_projects WHERE id = ?", (id,)).fetchone()
        if row:
            project = dict(row)

    # 기본 프리셋 찾기
    selected_preset = next((p for p in BANNER_PRESETS if p["id"] == preset), BANNER_PRESETS[0])

    return templates.TemplateResponse(
        request=request,
        name="banner/editor.html",
        context={
            "request": request,
            "page_title": "배너 편집기",
            "user_name": u.get("name", ""),
            "project": project,
            "project_id": id if project else 0,
            "presets": BANNER_PRESETS,
            "default_preset": selected_preset,
        }
    )


@router.get("/banner/api/{project_id}")
async def get_project(project_id: int, u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    row = conn.execute("SELECT * FROM banner_projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="배너 프로젝트를 찾을 수 없습니다.")
    return JSONResponse(dict(row))


@router.post("/banner/api/save")
async def save_project(request: Request, u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="유효하지 않은 요청 데이터입니다.")

    project_id = int(data.get("id") or 0)
    title = (data.get("title") or "새 배너").strip()
    category = data.get("category") or "web"
    preset_name = data.get("preset_name") or "가로형 배너"
    width = int(data.get("width") or 1200)
    height = int(data.get("height") or 400)

    canvas_json = data.get("canvas_json")
    if isinstance(canvas_json, (list, dict)):
        canvas_json = json.dumps(canvas_json, ensure_ascii=False)
    elif not canvas_json:
        canvas_json = "{}"

    thumbnail = data.get("thumbnail") or ""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_id = u.get("id")
    user_name = u.get("name", "")

    if project_id > 0:
        # 기존 수정
        conn.execute("""
            UPDATE banner_projects
            SET title = ?, category = ?, preset_name = ?, width = ?, height = ?, canvas_json = ?, thumbnail = ?, updated_at = ?
            WHERE id = ?
        """, (title, category, preset_name, width, height, canvas_json, thumbnail, now_str, project_id))
        conn.commit()
        return JSONResponse({"ok": True, "id": project_id, "message": "배너가 저장되었습니다."})
    else:
        # 신규 생성
        cur = conn.execute("""
            INSERT INTO banner_projects (title, category, preset_name, width, height, canvas_json, thumbnail, created_by, created_by_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, category, preset_name, width, height, canvas_json, thumbnail, user_id, user_name, now_str, now_str))
        conn.commit()
        new_id = cur.lastrowid
        return JSONResponse({"ok": True, "id": new_id, "message": "새 배너가 생성되었습니다."})


@router.post("/banner/api/{project_id}/delete")
async def delete_project(project_id: int, u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    conn.execute("DELETE FROM banner_projects WHERE id = ?", (project_id,))
    conn.commit()
    return JSONResponse({"ok": True, "message": "배너가 삭제되었습니다."})


@router.post("/banner/api/{project_id}/duplicate")
async def duplicate_project(project_id: int, u: dict = Depends(require_login), conn=Depends(get_db)):
    _ensure_table(conn)
    row = conn.execute("SELECT * FROM banner_projects WHERE id = ?", (project_id,))
    orig = row.fetchone()
    if not orig:
        raise HTTPException(status_code=404, detail="원본 배너를 찾을 수 없습니다.")

    orig_dict = dict(orig)
    new_title = f"{orig_dict['title']} (복사본)"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur = conn.execute("""
        INSERT INTO banner_projects (title, category, preset_name, width, height, canvas_json, thumbnail, created_by, created_by_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        new_title, orig_dict["category"], orig_dict["preset_name"],
        orig_dict["width"], orig_dict["height"], orig_dict["canvas_json"],
        orig_dict["thumbnail"], u.get("id"), u.get("name", ""), now_str, now_str
    ))
    conn.commit()
    return JSONResponse({"ok": True, "id": cur.lastrowid, "message": "배너가 복제되었습니다."})
