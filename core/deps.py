from fastapi import Request, Depends
from fastapi.templating import Jinja2Templates

from core.db import get_sqlite

templates = Jinja2Templates(directory="templates")


class AuthRedirect(Exception):
    def __init__(self, url="/login"):
        self.url = url


def check_login(request):
    return request.session.get("logined", False)


def get_current_user(request):
    return {
        "user_id": request.session.get("user_id", 1),
        "user_name": request.session.get("user_name", ""),
        "user_role": request.session.get("user_role", "employee"),
    }


def get_db():
    conn = get_sqlite()
    try:
        yield conn
    finally:
        conn.close()


def require_login(request: Request):
    if not request.session.get("logined", False):
        raise AuthRedirect("/login")
    return get_current_user(request)


def require_staff(request: Request):
    user = require_login(request)
    if user["user_role"] != "platform_staff":
        raise AuthRedirect("/")
    return user


def require_client(allowed_roles=None):
    def dep(request: Request):
        user = require_login(request)
        if user["user_role"] != "client":
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
        company_id = get_company_id_for_client(conn, user["user_id"])
        if company_id is None:
            raise AuthRedirect("/")
        return {**user, "company_id": company_id}
    return dep


def require_client_hr_with_company(request: Request, conn=Depends(get_db)):
    from core.attendance import get_company_id_for_client

    user = require_client_hr(request)
    company_id = get_company_id_for_client(conn, user["user_id"])
    if company_id is None:
        raise AuthRedirect("/")
    return {**user, "company_id": company_id}


def get_employee_id(conn, user_id):
    row = conn.execute(
        "SELECT id FROM employees WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row["id"] if row else None
