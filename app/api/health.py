"""健康检查（启动器依赖此端点判断服务是否就绪）。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from .. import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "personal-assistant", "version": __version__}


@router.get("/startup")
def startup_status(request: Request) -> dict:
    return request.app.state.module_startup.snapshot()
