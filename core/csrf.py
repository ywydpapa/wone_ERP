import secrets

from fastapi import HTTPException, Request
from markupsafe import Markup

_FORM_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


def ensure_token(request):
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token


async def verify_csrf(request: Request):
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return
    ct = request.headers.get("content-type", "")
    if not any(ct.startswith(t) for t in _FORM_TYPES):
        return
    form = await request.form()
    form_token = form.get("csrf_token", "")
    session_token = request.session.get("csrf_token", "")
    if not session_token or not form_token or not secrets.compare_digest(session_token, form_token):
        raise HTTPException(status_code=403, detail="CSRF 토큰이 유효하지 않습니다")


def csrf_input_html(token):
    return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')
