"""存储大小只读接口，不接受客户端文件路径。"""
from fastapi import APIRouter, Depends

from .deps import get_settings
from ..config import Settings
from ..services.storage_inventory import storage_overview

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/overview")
def overview(settings: Settings = Depends(get_settings)):
    from ..morning_report.config import get_mr_settings
    morning = get_mr_settings()
    return storage_overview(settings, morning_filename=morning.db_filename,
                            cache_hours=morning.stage_cache_ttl_hours)
