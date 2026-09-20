import json
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from core.csrf import verify_csrf
from core.deps import AuthRedirect, templates, check_idle
from core.db import get_sqlite
from core.notification import get_unread_count

from routers.files import router as files_router
from routers import auth, dashboard, community
from routers.hr import router as hr_router
from routers.platform import router as platform_router
from routers.platform_work import router as platform_work_router
from routers.client import router as client_router
from routers.client_hr import router as client_hr_router
from routers.client_payroll import router as client_payroll_router
from routers.client_leave import router as client_leave_router
from routers.client_eval import router as client_eval_router
from routers.client_form import router as client_form_router
from routers.worker import router as worker_router
from routers.worker_message import router as message_router
from routers.slip import router as slip_router
from routers.erp_doc import router as erp_doc_router
from routers.erp_dashboard import router as erp_dashboard_router
from routers.erp_master import router as erp_master_router
from routers.erp_purchase import router as erp_purchase_router
from routers.erp_pr import router as erp_pr_router
from routers.erp_sales import router as erp_sales_router
from routers.erp_production import router as erp_production_router
from routers.erp_accounting import router as erp_accounting_router
from routers.accessibility import router as accessibility_router
from routers.mypage import router as mypage_router
from init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="WONE ERP", lifespan=lifespan, dependencies=[Depends(check_idle), Depends(verify_csrf)])


@app.exception_handler(AuthRedirect)
async def handle_auth_redirect(request: Request, exc: AuthRedirect):
    return RedirectResponse(url=exc.url, status_code=303)


ERROR_MESSAGES = {
    404: ("페이지를 찾을 수 없습니다", "요청하신 페이지가 존재하지 않거나 이동되었습니다."),
    403: ("접근 권한이 없습니다", "이 페이지에 접근할 수 있는 권한이 없습니다."),
    500: ("서버 오류", "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."),
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    title, message = ERROR_MESSAGES.get(exc.status_code, ("오류", str(exc.detail)))
    return templates.TemplateResponse(
        request=request, name="error.html",
        context={"request": request, "page_title": title, "code": exc.status_code, "title": title, "message": message},
        status_code=exc.status_code,
    )

SESSION_SECRET = os.getenv("SESSION_SECRET_KEY")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET_KEY가 설정되지 않았습니다")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=os.getenv("ENV") == "production",
)

@app.middleware("http")
async def inject_nav_counts(request: Request, call_next):
    if not request.url.path.startswith("/static") and request.cookies.get("session"):
        try:
            logined = request.session.get("logined", False)
        except Exception:
            logined = False

        if logined:
            conn = get_sqlite()
            try:
                uid = request.session.get("id")

                request.state.unread_messages = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE user_id=? AND direction='in' AND is_read=0",
                    (uid,),
                ).fetchone()[0]

                request.state.notif_count = get_unread_count(conn, uid)

                row = conn.execute(
                    "SELECT accessibility_settings FROM users WHERE id=?", (uid,)
                ).fetchone()
                request.state.accessibility = json.loads(row["accessibility_settings"]) if row and row["accessibility_settings"] else {}
            except Exception:
                request.state.unread_messages = 0
                request.state.notif_count = 0
                request.state.accessibility = {}
            finally:
                conn.close()
        else:
            request.state.unread_messages = 0
            request.state.notif_count = 0
            request.state.accessibility = {}
    else:
        request.state.unread_messages = 0
        request.state.notif_count = 0
        request.state.accessibility = {}

    return await call_next(request)


app.mount("/static", StaticFiles(directory="static"), name="static")

# 라우터
app.include_router(files_router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(hr_router)
app.include_router(platform_work_router)
app.include_router(platform_router)
app.include_router(community.router)
app.include_router(client_router)
app.include_router(client_hr_router)
app.include_router(client_payroll_router)
app.include_router(client_leave_router)
app.include_router(client_eval_router)
app.include_router(client_form_router)
app.include_router(worker_router)
app.include_router(message_router)
app.include_router(slip_router)
app.include_router(erp_doc_router)
app.include_router(erp_dashboard_router)
app.include_router(erp_master_router)
app.include_router(erp_purchase_router)
app.include_router(erp_pr_router)
app.include_router(erp_sales_router)
app.include_router(erp_production_router)
app.include_router(erp_accounting_router)
app.include_router(accessibility_router)
app.include_router(mypage_router)
