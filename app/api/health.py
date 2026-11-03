"""健康检查（启动器依赖此端点判断服务是否就绪）。"""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "personal-hub", "version": __version__}
