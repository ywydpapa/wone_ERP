from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def check_login(request: Request) -> bool:
    return request.session.get("logined", False)


def get_current_user(request: Request) -> dict:
    return {
        "user_id": request.session.get("user_id", 1),
        "user_name": request.session.get("user_name", ""),
        "user_role": request.session.get("user_role", "employee"),
    }
