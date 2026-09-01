from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import JSONResponse
from core.deps import get_db, require_login, templates
from core.constants import POST_CATEGORIES

router = APIRouter()


@router.get("/community", response_class=HTMLResponse)
async def community(request: Request, category: str = "all", q: str = "", page: int = 1, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    per_page = 10
    sql = """SELECT p.*,
        (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comment_count,
        (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS like_count
        FROM posts p WHERE 1=1"""
    params = []
    count_params = []
    count_sql = "SELECT COUNT(*) FROM posts p WHERE 1=1"
    if category != "all":
        sql += " AND p.category=?"; params.append(category)
        count_sql += " AND p.category=?"; count_params.append(category)
    if q:
        sql += " AND (p.title LIKE '%'||?||'%' OR p.content LIKE '%'||?||'%')"; params += [q, q]
        count_sql += " AND (p.title LIKE '%'||?||'%' OR p.content LIKE '%'||?||'%')"; count_params += [q, q]
    total = conn.execute(count_sql, count_params).fetchone()[0]
    sql += " ORDER BY p.id DESC LIMIT ? OFFSET ?"; params += [per_page, (page - 1) * per_page]
    posts = [dict(r) for r in conn.execute(sql, params).fetchall()]
    my_post_count = conn.execute("SELECT COUNT(*) FROM posts WHERE user_id=?", (uid,)).fetchone()[0]
    my_comment_count = conn.execute("SELECT COUNT(*) FROM comments WHERE user_id=?", (uid,)).fetchone()[0]
    my_like_received = conn.execute(
        "SELECT COUNT(*) FROM post_likes l JOIN posts p ON p.id=l.post_id WHERE p.user_id=?", (uid,)
    ).fetchone()[0]
    return templates.TemplateResponse(
        request=request, name="community/community.html", context={
            "request": request, "page_title": "커뮤니티",
            "user_name": u["user_name"],
            "posts": posts, "categories": POST_CATEGORIES,
            "current_category": category, "q": q, "page": page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "my_post_count": my_post_count,
            "my_comment_count": my_comment_count,
            "my_like_received": my_like_received,
            "user_dept": u.get("dept", ""),
            "user_position": u.get("position", ""),
        }
    )


@router.get("/write_post", response_class=HTMLResponse)
async def write_post_page(request: Request, u: dict = Depends(require_login)):
    return templates.TemplateResponse(
        request=request, name="community/write_post.html", context={
            "request": request, "page_title": "새 글 작성",
            "user_name": u["user_name"],
        }
    )


@router.get("/my_posts", response_class=HTMLResponse)
async def my_posts(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    posts = [dict(r) for r in conn.execute(
        "SELECT * FROM posts WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()]
    comments = [dict(r) for r in conn.execute(
        "SELECT c.*, p.title AS post_title FROM comments c JOIN posts p ON p.id=c.post_id WHERE c.user_id=? ORDER BY c.created_at DESC",
        (uid,)).fetchall()]
    return templates.TemplateResponse(
        request=request, name="community/my_posts.html", context={
            "request": request, "page_title": "내가 쓴 글",
            "posts": posts, "comments": comments,
            "user_name": u["user_name"],
        }
    )


@router.get("/my_bookmarks", response_class=HTMLResponse)
async def my_bookmarks(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    rows = conn.execute(
        "SELECT p.* FROM posts p JOIN bookmarks b ON b.post_id=p.id AND b.user_id=? ORDER BY p.created_at DESC",
        (uid,)
    ).fetchall()
    return templates.TemplateResponse(
        request=request, name="community/my_bookmarks.html", context={
            "request": request, "page_title": "북마크",
            "posts": [dict(r) for r in rows],
            "user_name": u["user_name"],
        }
    )


@router.get("/post/{post_id}", response_class=HTMLResponse)
async def post_detail(request: Request, post_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    conn.execute("UPDATE posts SET views=views+1 WHERE id=?", (post_id,))
    conn.commit()
    row = conn.execute(
        "SELECT * FROM posts WHERE id=?",
        (post_id,)
    ).fetchone()
    if not row:
        return HTMLResponse("<h2>게시글을 찾을 수 없습니다</h2><a href='/community'>돌아가기</a>", status_code=404)
    comments = [dict(c) for c in conn.execute(
        "SELECT * FROM comments WHERE post_id=? ORDER BY id ASC", (post_id,)).fetchall()]
    like_count = conn.execute("SELECT COUNT(*) FROM post_likes WHERE post_id=?", (post_id,)).fetchone()[0]
    liked = conn.execute("SELECT 1 FROM post_likes WHERE post_id=? AND user_id=?", (post_id, uid)).fetchone() is not None
    bookmarked = conn.execute("SELECT 1 FROM bookmarks WHERE post_id=? AND user_id=?", (post_id, uid)).fetchone() is not None
    return templates.TemplateResponse(
        request=request, name="community/post_detail.html", context={
            "request": request, "page_title": dict(row)["title"],
            "post": dict(row), "comments": comments,
            "like_count": like_count, "liked": liked, "bookmarked": bookmarked,
            "categories": POST_CATEGORIES,
            "user_name": u["user_name"],
            "session_uid": uid,
        }
    )


@router.post("/api/posts")
async def create_post(
    request: Request,
    category: str = Form("general"),
    title: str = Form(""),
    content: str = Form(""),
    u: dict = Depends(require_login),
    conn = Depends(get_db),
):
    uid = u["user_id"]
    if category == "notice" and u["user_role"] != "platform_staff":
        return RedirectResponse(url="/community", status_code=303)
    user = conn.execute("SELECT name, dept FROM users WHERE id=?", (uid,)).fetchone()
    author = user["name"] if user else ""
    dept = user["dept"] if user else ""
    conn.execute(
        "INSERT INTO posts (user_id, category, title, content, author, dept) VALUES (?,?,?,?,?,?)",
        (uid, category, title, content, author, dept),
    )
    conn.commit()
    return RedirectResponse(url="/community", status_code=303)


@router.get("/api/posts")
async def list_posts(request: Request, u: dict = Depends(require_login), conn = Depends(get_db)):
    rows = conn.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


@router.post("/api/posts/{post_id}/comments")
async def add_comment(request: Request, post_id: int, content: str = Form(...), u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    user_row = conn.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
    author = user_row["name"] if user_row else u["user_name"]
    conn.execute(
        "INSERT INTO comments (post_id, user_id, author, content) VALUES (?, ?, ?, ?)",
        (post_id, uid, author, content)
    )
    conn.commit()
    return RedirectResponse(url=f"/post/{post_id}", status_code=303)


@router.post("/api/posts/{post_id}/like")
async def toggle_like(request: Request, post_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    existing = conn.execute("SELECT 1 FROM post_likes WHERE post_id=? AND user_id=?", (post_id, uid)).fetchone()
    if existing:
        conn.execute("DELETE FROM post_likes WHERE post_id=? AND user_id=?", (post_id, uid))
        liked = False
    else:
        conn.execute("INSERT INTO post_likes (post_id, user_id) VALUES (?, ?)", (post_id, uid))
        liked = True
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM post_likes WHERE post_id=?", (post_id,)).fetchone()[0]
    return {"liked": liked, "count": count}


@router.post("/api/posts/{post_id}/bookmark")
async def toggle_bookmark(request: Request, post_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    existing = conn.execute("SELECT 1 FROM bookmarks WHERE post_id=? AND user_id=?", (post_id, uid)).fetchone()
    if existing:
        conn.execute("DELETE FROM bookmarks WHERE post_id=? AND user_id=?", (post_id, uid))
        bookmarked = False
    else:
        conn.execute("INSERT INTO bookmarks (post_id, user_id) VALUES (?, ?)", (post_id, uid))
        bookmarked = True
    conn.commit()
    return {"bookmarked": bookmarked}


@router.delete("/api/posts/{post_id}")
async def delete_post(request: Request, post_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    row = conn.execute("SELECT user_id FROM posts WHERE id=?", (post_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    if row["user_id"] != uid:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    conn.execute("DELETE FROM comments WHERE post_id=?", (post_id,))
    conn.execute("DELETE FROM post_likes WHERE post_id=?", (post_id,))
    conn.execute("DELETE FROM bookmarks WHERE post_id=?", (post_id,))
    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()
    return JSONResponse({"ok": True})


@router.delete("/api/comments/{comment_id}")
async def delete_comment(request: Request, comment_id: int, u: dict = Depends(require_login), conn = Depends(get_db)):
    uid = u["user_id"]
    row = conn.execute("SELECT user_id FROM comments WHERE id=?", (comment_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    if row["user_id"] != uid:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    conn.execute("DELETE FROM comments WHERE id=?", (comment_id,))
    conn.commit()
    return JSONResponse({"ok": True})
