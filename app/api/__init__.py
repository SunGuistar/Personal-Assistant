"""API 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from .cleanup import router as cleanup_router
from .github import router as github_router
from .health import router as health_router
from .infos import infos_router, memos_router
from .jobs import router as jobs_router
from .plans import router as plans_router
from .reading import notes_router, router as reading_router
from .tasks import router as tasks_router
from .wechat import router as wechat_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(plans_router)
api_router.include_router(tasks_router)
api_router.include_router(jobs_router)
api_router.include_router(reading_router)
api_router.include_router(notes_router)
api_router.include_router(wechat_router)
api_router.include_router(cleanup_router)
api_router.include_router(infos_router)
api_router.include_router(memos_router)
api_router.include_router(github_router)
