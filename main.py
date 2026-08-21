import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from routers import auth, dashboard, community
from routers.hr import router as hr_router
from routers.platform import router as platform_router
from routers.client import router as client_router
from routers.worker import router as worker_router
from routers.mypage import router as mypage_router
from init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="WONE ERP", lifespan=lifespan)

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
app.include_router(worker_router)
app.include_router(mypage_router)
