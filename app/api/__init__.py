"""API 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from .health import router as health_router
from .tasks import router as tasks_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(tasks_router)
