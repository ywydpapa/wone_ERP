from datetime import timedelta

from core.auth import DUMMY_HASH, hash_pw, verify_pw, is_legacy
from core.tz import now_kst
from core.rate_limit import get_client_ip, check_login_rate, record_login_attempt, clear_login_attempts
from core import audit
from core.books import book_of

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from core.db import get_sqlite
from core.deps import check_login, templates

router = APIRouter()

LOCK_FAILS = 5
LOCK_WINDOW = 10  # 분
LOCK_MIN = 30  # 분


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
        acct = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        # 미존재 계정도 동일 연산 수행. 응답시간으로 계정 존재 여부 노출 방지
        pw_ok = verify_pw(password, acct["password"] if acct else DUMMY_HASH)
        row = acct if pw_ok else None
        if row and is_legacy(row["password"]):
            conn.execute(
                "UPDATE users SET password=? WHERE id=?", (hash_pw(password), row["id"])
            )
            conn.commit()

        now = now_kst().strftime("%Y-%m-%d %H:%M:%S")

        # 잠금 중이면 비번이 맞아도 실패 처리
        if acct and acct["locked_until"] and acct["locked_until"] > now:
            conn.execute(
                "INSERT INTO login_attempts (username, ip, ok, at) VALUES (?,?,0,?)", (username, ip, now)
            )
            audit.log(conn, acct["id"], "login_fail", "user", acct["id"], "잠금 중 시도", ip=ip)
            conn.commit()
            record_login_attempt(ip)
            return RedirectResponse(url="/login?error=locked", status_code=303)

        if row and row["role"] == "client":
            cu = conn.execute(
                "SELECT client_role FROM client_users WHERE user_id=?", (row["id"],)
            ).fetchone()
            client_role = cu["client_role"] if cu else "all"
        else:
            client_role = None

        if row:
            conn.execute(
                "INSERT INTO login_attempts (username, ip, ok, at) VALUES (?,?,1,?)", (username, ip, now)
            )
            audit.log(conn, row["id"], "login", "user", row["id"], username, company_id=book_of(conn, row), ip=ip)
            conn.commit()
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

        conn.execute(
            "INSERT INTO login_attempts (username, ip, ok, at) VALUES (?,?,0,?)", (username, ip, now)
        )
        cutoff = (now_kst() - timedelta(minutes=LOCK_WINDOW)).strftime("%Y-%m-%d %H:%M:%S")
        last_ok = conn.execute(
            "SELECT at FROM login_attempts WHERE username=? AND ok=1 ORDER BY at DESC LIMIT 1", (username,)
        ).fetchone()
        since = last_ok["at"] if last_ok else "0000-00-00 00:00:00"
        fails = conn.execute(
            "SELECT COUNT(*) c FROM login_attempts WHERE username=? AND ok=0 AND at>? AND at>?",
            (username, since, cutoff)
        ).fetchone()["c"]

        if fails >= LOCK_FAILS:
            if acct:
                locked_until = (now_kst() + timedelta(minutes=LOCK_MIN)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("UPDATE users SET locked_until=? WHERE id=?", (locked_until, acct["id"]))
                audit.log(conn, acct["id"], "login_lock", "user", acct["id"], username, ip=ip)
            conn.commit()
            record_login_attempt(ip)
            return RedirectResponse(url="/login?error=locked", status_code=303)

        audit.log(conn, acct["id"] if acct else None, "login_fail", "user",
                   acct["id"] if acct else None, username, ip=ip)
        conn.commit()
    finally:
        conn.close()
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
    uid = request.session.get("id")
    username = request.session.get("username")
    if uid:
        conn = get_sqlite()
        try:
            audit.log(conn, uid, "logout", "user", uid, username, ip=get_client_ip(request))
            conn.commit()
        finally:
            conn.close()
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
