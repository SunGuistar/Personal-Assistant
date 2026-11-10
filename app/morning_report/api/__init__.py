"""晨报 API 路由聚合（/api/morning/*）。薄层：参数校验、调用 services、统一异常。"""

from __future__ import annotations

from fastapi import APIRouter

from .deps import get_mr_session, get_mr_settings, get_hub_session
from .memory import router as memory_router
from .runs import router as runs_router
from .status import router as status_router

morning_router = APIRouter(prefix="/api/morning", tags=["morning-report"])
morning_router.include_router(status_router)
morning_router.include_router(memory_router)
morning_router.include_router(runs_router)

__all__ = ["morning_router", "get_mr_session", "get_mr_settings", "get_hub_session"]
