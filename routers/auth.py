from core.auth import DUMMY_HASH, hash_pw, verify_pw, is_legacy
from core.tz import now_kst
from core.rate_limit import get_client_ip, check_login_rate, record_login_attempt, clear_login_attempts

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
    ip = get_client_ip(request)
    if check_login_rate(ip):
        return RedirectResponse(url="/login?error=rate", status_code=303)
    conn = get_sqlite()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        # 미존재 계정도 동일 연산 수행. 응답시간으로 계정 존재 여부 노출 방지
        if not verify_pw(password, row["password"] if row else DUMMY_HASH):
            row = None
        if row and is_legacy(row["password"]):
            conn.execute(
                "UPDATE users SET password=? WHERE id=?", (hash_pw(password), row["id"])
            )
            conn.commit()
        if row and row["role"] == "client":
            cu = conn.execute(
                "SELECT client_role FROM client_users WHERE user_id=?", (row["id"],)
            ).fetchone()
            client_role = cu["client_role"] if cu else "all"
        else:
            client_role = None
    finally:
        conn.close()
    if row:
        clear_login_attempts(ip)
        request.session["logined"] = True
        request.session["id"] = row["id"]
        request.session["username"] = row["username"]
        request.session["name"] = row["name"]
        request.session["role"] = row["role"]
        if dict(row).get("is_hr_admin"):
            request.session["is_hr_admin"] = True
        if client_role is not None:
            request.session["client_role"] = client_role
        return RedirectResponse(url="/", status_code=303)
    record_login_attempt(ip)
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
        hashed = hash_pw(password)
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
