import hashlib

from core.tz import now_kst

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from core.db import get_sqlite
from core.deps import check_login, templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if check_login(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request, name="/login/login.html", context={
            "request": request, "page_title": "로그인", "error": error,
        }
    )


@router.post("/login_check")
async def login_check(request: Request, username: str = Form(...), password: str = Form(...)):
    hashed = hashlib.sha256(password.encode()).hexdigest()
    conn = get_sqlite()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?", (username, hashed)
        ).fetchone()
    finally:
        conn.close()
    if row:
        request.session["logined"] = True
        request.session["user_id"] = row["id"]
        request.session["username"] = row["username"]
        request.session["user_name"] = row["name"]
        request.session["user_role"] = row["role"]
        if row["role"] == "client":
            conn2 = get_sqlite()
            try:
                cu = conn2.execute(
                    "SELECT client_role FROM client_users WHERE user_id=?", (row["id"],)
                ).fetchone()
                request.session["client_role"] = cu["client_role"] if cu else "all"
            finally:
                conn2.close()
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url="/login?error=1", status_code=303)


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="/login/terms.html", context={"request": request}
    )


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="/login/privacy.html", context={"request": request}
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, error: str = ""):
    return templates.TemplateResponse(
        request=request, name="/login/signup.html", context={
            "request": request, "page_title": "회원가입", "error": error,
        }
    )


@router.post("/signup")
async def signup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
    dept: str = Form("경영지원팀"),
    agree_terms: str = Form(None),
    agree_privacy: str = Form(None),
    agree_marketing: str = Form(None),
):
    if not agree_terms or not agree_privacy:
        return RedirectResponse(url="/signup?error=consent", status_code=303)

    now = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    marketing_at = now if agree_marketing else None

    conn = get_sqlite()
    try:
        hashed = hashlib.sha256(password.encode()).hexdigest()
        conn.execute(
            """INSERT INTO users
               (username, password, name, dept, agreed_terms_at, agreed_privacy_at, agreed_marketing_at)
               VALUES (?,?,?,?,?,?,?)""",
            (username, hashed, name, dept, now, now, marketing_at)
        )
        conn.commit()
    except Exception:
        return RedirectResponse(url="/signup?error=dup", status_code=303)
    finally:
        conn.close()
    return RedirectResponse(url="/login", status_code=303)
