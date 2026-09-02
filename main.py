import json
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from core.deps import AuthRedirect, get_employee_id
from core.db import get_sqlite

from routers import auth, dashboard, community
from routers.hr import router as hr_router
from routers.platform import router as platform_router
from routers.client import router as client_router
from routers.client_hr import router as client_hr_router
from routers.client_payroll import router as client_payroll_router
from routers.client_leave import router as client_leave_router
from routers.client_eval import router as client_eval_router
from routers.worker import router as worker_router
from routers.worker_message import router as message_router
from routers.slip import router as slip_router
from routers.erp_doc import router as erp_doc_router
from routers.erp_dashboard import router as erp_dashboard_router
from routers.accessibility import router as accessibility_router
from routers.mypage import router as mypage_router
from init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="WONE ERP", lifespan=lifespan)


@app.exception_handler(AuthRedirect)
async def handle_auth_redirect(request: Request, exc: AuthRedirect):
    return RedirectResponse(url=exc.url, status_code=303)

# 세션
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "erp-dev-key"),
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
                uid = request.session.get("user_id")
                role = request.session.get("user_role", "worker")

                request.state.unread_messages = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE user_id=? AND direction='in' AND is_read=0",
                    (uid,),
                ).fetchone()[0]

                if role == "platform_staff":
                    request.state.notif_count = conn.execute(
                        "SELECT COUNT(*) FROM work_requests WHERE status='pending'"
                    ).fetchone()[0]
                elif role == "client":
                    cu = conn.execute(
                        "SELECT company_id FROM client_users WHERE user_id=?", (uid,)
                    ).fetchone()
                    cid = cu["company_id"] if cu else None
                    if cid:
                        request.state.notif_count = conn.execute(
                            "SELECT COUNT(*) FROM leave_requests lr "
                            "JOIN employees e ON lr.employee_id=e.id "
                            "WHERE e.company_id=? AND lr.status='pending'",
                            (cid,),
                        ).fetchone()[0]
                    else:
                        request.state.notif_count = 0
                else:
                    eid = get_employee_id(conn, uid)
                    if eid:
                        request.state.notif_count = conn.execute(
                            "SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status='assigned'",
                            (eid,),
                        ).fetchone()[0]
                    else:
                        request.state.notif_count = 0

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


# 정적 파일
app.mount("/static", StaticFiles(directory="static"), name="static")

# 라우터
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(hr_router)
app.include_router(platform_router)
app.include_router(community.router)
app.include_router(client_router)
app.include_router(client_hr_router)
app.include_router(client_payroll_router)
app.include_router(client_leave_router)
app.include_router(client_eval_router)
app.include_router(worker_router)
app.include_router(message_router)
app.include_router(slip_router)
app.include_router(erp_doc_router)
app.include_router(erp_dashboard_router)
app.include_router(accessibility_router)
app.include_router(mypage_router)
