"""技术资讯 API（薄层：校验 → service → 出 schema；PRD §2.2）。

刷新是后台任务（AGENTS §4.4）：POST /refresh 提交 TaskRunner（kind
news.refresh，同 kind 未完成自动 409），进度与结果经 /api/jobs/{id} 查询；
最近一次成功刷新经 GET /news/status 读取（供前端判断是否需要自动刷新）。
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..schemas.news import (
    NewsItemListOut,
    NewsItemOut,
    NewsItemPatch,
    NewsRefreshOut,
    NewsSourceIn,
    NewsSourceOut,
    NewsSourcePatch,
    NewsSort,
    NewsStatusOut,
)
from ..services import news_service
from .deps import get_session, get_task_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news"])


# ---------- 条目 ----------

@router.get("/items", response_model=NewsItemListOut)
def list_items(
    page: int = 1,
    page_size: int = 30,
    topic: str | None = None,
    source: str | None = None,
    sort: NewsSort = "latest",
    since: str | None = None,
    until: str | None = None,
    favorite: bool | None = None,
    unread: bool | None = None,
    session: Session = Depends(get_session),
):
    return news_service.list_items(
        session,
        page=page,
        page_size=page_size,
        topic=topic,
        source=source,
        sort=sort,
        since=since,
        until=until,
        favorite=favorite,
        unread=unread,
    )


@router.patch("/items/{item_id}", response_model=NewsItemOut)
def update_item(item_id: int, payload: NewsItemPatch, session: Session = Depends(get_session)):
    return news_service.update_item(session, item_id, payload.model_dump(exclude_unset=True))


# ---------- 来源 ----------

@router.get("/sources", response_model=list[NewsSourceOut])
def list_sources(session: Session = Depends(get_session)):
    return news_service.list_sources(session)


@router.post("/sources", response_model=NewsSourceOut, status_code=201)
def create_source(payload: NewsSourceIn, session: Session = Depends(get_session)):
    return news_service.create_source(session, **payload.model_dump())


@router.patch("/sources/{source_id}", response_model=NewsSourceOut)
def update_source(source_id: int, payload: NewsSourcePatch, session: Session = Depends(get_session)):
    return news_service.update_source(session, source_id, payload.model_dump(exclude_unset=True))


# ---------- 刷新 ----------

@router.post("/refresh", response_model=NewsRefreshOut, status_code=202)
def start_refresh(request: Request, runner=Depends(get_task_runner)):
    """提交刷新任务；同 kind 未完成 → 409（TaskRunner 重复提交保护）。"""

    session_factory = request.app.state.session_factory

    def job(progress_cb):
        with session_factory() as job_session:
            return news_service.refresh_all(job_session, progress_cb=progress_cb)

    task = runner.submit(news_service.REFRESH_KIND, {}, job)
    return {"task_id": task.id, "status": task.status}


@router.get("/status", response_model=NewsStatusOut)
def refresh_status(request: Request, session: Session = Depends(get_session)):
    """最近成功刷新时间与是否需要刷新（供前端进入页面时自动触发）。"""

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
