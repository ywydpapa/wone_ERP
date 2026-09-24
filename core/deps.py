import logging
import os
import time

from fastapi import Request, Depends

log = logging.getLogger("wone.auth")
from fastapi.templating import Jinja2Templates

from core.csrf import ensure_token, csrf_input_html
from core.db import get_sqlite


def csrf_context(request):
    try:
        token = ensure_token(request)
    except Exception:
        return {"csrf_input": "", "csrf_token": ""}
    return {"csrf_input": csrf_input_html(token), "csrf_token": token}


templates = Jinja2Templates(directory="templates", context_processors=[csrf_context])


class AuthRedirect(Exception):
    def __init__(self, url="/login"):
        self.url = url


IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "1800"))
# localhost는 포트 달라도 쿠키 공유됨. recruit랑 이름 겹치면 세션 깨짐
SESSION_COOKIE = "erp_session"


def check_idle(request: Request):
    if not request.session.get("logined"):
        # 세션 쿠키는 있는데 세션이 비어있으면 깨진 쿠키 - 교체
        if request.cookies.get(SESSION_COOKIE) and not request.session:
            log.warning("broken cookie: %s %s", request.method, request.url.path)
            request.session["_invalid"] = 1
        return
    now = time.time()
    last = request.session.get("last_seen")
    if last and now - last > IDLE_TIMEOUT:
        log.info("timeout: user=%s idle=%.0fs", request.session.get("id"), now - last)
        request.session.clear()
        raise AuthRedirect("/login?error=timeout")
    request.session["last_seen"] = now


def require_login(request: Request):
    if not request.session.get("logined", False):
        has_cookie = bool(request.cookies.get(SESSION_COOKIE))
        keys = list(request.session.keys())
        print(f"[AUTH] BLOCKED {request.method} {request.url.path} | cookie={has_cookie} session_keys={keys}")
        raise AuthRedirect("/login")
    return get_current_user(request)


def check_login(request):
    return request.session.get("logined", False)


def get_current_user(request):
    return {
        "id": request.session.get("id", 1),
        "name": request.session.get("name", ""),
        "role": request.session.get("role", "employee"),
        "is_hr_admin": request.session.get("is_hr_admin", False),
    }


def get_db():
    conn = get_sqlite()
    try:
        yield conn
    finally:
        conn.close()




def require_staff(request: Request):
    user = require_login(request)
    if user["role"] != "platform_staff":
        raise AuthRedirect("/")
    return user


def require_client(allowed_roles=None):
    def dep(request: Request):
        user = require_login(request)
        if user["role"] != "client":
            raise AuthRedirect("/")
        if allowed_roles:
            client_role = request.session.get("client_role", "all")
            if client_role != "all" and client_role not in allowed_roles:
                raise AuthRedirect("/")
        return user
    return dep


def require_client_hr(request: Request):
    return require_client(allowed_roles=("hr",))(request)


def require_client_with_company(allowed_roles=None):
    from core.attendance import get_company_id_for_client

    def dep(request: Request, conn=Depends(get_db)):
        user = require_client(allowed_roles)(request)
        company_id = get_company_id_for_client(conn, user["id"])
        if company_id is None:
            raise AuthRedirect("/")
        return {**user, "company_id": company_id}
    return dep


def require_client_hr_with_company(request: Request, conn=Depends(get_db)):
    from core.attendance import get_company_id_for_client

    user = require_client_hr(request)
    company_id = get_company_id_for_client(conn, user["id"])
    if company_id is None:
        raise AuthRedirect("/")
    return {**user, "company_id": company_id}


def require_worker(request: Request, conn=Depends(get_db)):
    user = require_login(request)
    if user["role"] != "worker":
        raise AuthRedirect("/")
    emp_id = get_employee_id(conn, user["id"])
    return {**user, "employee_id": emp_id}



def get_employee_id(conn, user_id):
    row = conn.execute(
        "SELECT id FROM employees WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row["id"] if row else None
