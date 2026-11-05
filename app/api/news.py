"""技术资讯 API（PRD §2.2 最终版：近期热门 TOP 10 + 外部导航）。

- GET /news/top：排行榜纯查询（本地缓存，不触发抓取），首页与资讯页共用；
- POST /news/refresh：TaskRunner 后台刷新（kind news.refresh，同 kind 409 防重），
  进度与结果经 /api/jobs/{id} 查询；刷新成功后同任务内继续批量中文翻译（仅 TOP 10 未翻译项）；
- GET /news/status：最近成功刷新时间 + 是否需要刷新（资讯页据此自动触发）。
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..schemas.news import NewsRefreshOut, NewsStatusOut, NewsTopOut
from ..services import news_service, news_translation
from .deps import get_session, get_task_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/top", response_model=NewsTopOut)
def get_top(session: Session = Depends(get_session)):
    return news_service.top_items(session)


@router.post("/refresh", response_model=NewsRefreshOut, status_code=202)
def start_refresh(request: Request, runner=Depends(get_task_runner)):
    """提交刷新任务；同 kind 未完成 → 409（TaskRunner 重复提交保护）。"""

    session_factory = request.app.state.session_factory

    def job(progress_cb):
        with session_factory() as job_session:
            result = news_service.refresh_all(job_session, progress_cb=progress_cb)
            translate_result = news_translation.translate_pending(job_session)
            result["translate"] = translate_result
            return result

    task = runner.submit(news_service.REFRESH_KIND, {}, job)
    return {"task_id": task.id, "status": task.status}


@router.get("/status", response_model=NewsStatusOut)
def refresh_status(request: Request, session: Session = Depends(get_session)):
    settings = request.app.state.settings
    last = news_service.last_refresh(session)
    stale = True
    if last and last.get("refreshed_at"):
        try:
            refreshed = datetime.fromisoformat(last["refreshed_at"])
            stale = (datetime.now() - refreshed).total_seconds() > settings.news_refresh_minutes * 60
        except ValueError:
            stale = True
    return {
        "last_refresh": last,
        "refresh_minutes": settings.news_refresh_minutes,
        "stale": stale,
    }
