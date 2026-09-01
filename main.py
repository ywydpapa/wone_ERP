import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from core.deps import AuthRedirect

from routers import auth, dashboard, community
from routers.hr import router as hr_router
from routers.platform import router as platform_router
from routers.client import router as client_router
from routers.client_hr import router as client_hr_router
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
app.include_router(worker_router)
app.include_router(message_router)
app.include_router(slip_router)
app.include_router(erp_doc_router)
app.include_router(erp_dashboard_router)
app.include_router(accessibility_router)
app.include_router(mypage_router)
