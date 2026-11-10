"""晨报 API 路由聚合（/api/morning/*）。薄层：参数校验、调用 services、统一异常。"""

from __future__ import annotations

from fastapi import APIRouter

from .assistant import router as assistant_router
from .deps import get_mr_session, get_mr_settings, get_hub_session
from .logs import router as logs_router
from .memory import router as memory_router
from .report import router as report_router
from .runs import router as runs_router
from .status import router as status_router

morning_router = APIRouter(prefix="/api/morning", tags=["morning-report"])
morning_router.include_router(status_router)
morning_router.include_router(memory_router)
morning_router.include_router(runs_router)
morning_router.include_router(report_router)
morning_router.include_router(assistant_router)
morning_router.include_router(logs_router)

__all__ = ["morning_router", "get_mr_session", "get_mr_settings", "get_hub_session"]
