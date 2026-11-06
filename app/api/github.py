"""GitHub 数据 API（阶段一）：状态、同步任务、年度贡献、日期详情。

职责边界：薄路由层。Token 只在任务线程内经适配器读取，本层与响应均不携带；
统计口径见 github_contrib 模块说明（Personal Hub 口径，非 GitHub 官方）。
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request

from ..adapters.github_source import GithubClient, token_configured
from ..exceptions import DomainError
from ..schemas.plan import IsoDate
from ..services import github_contrib, github_service
from .deps import get_session, get_task_runner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])

MIN_YEAR = 2008  # GitHub 上线年份，早于该年无意义


@router.get("/status")
def status(session=Depends(get_session)) -> dict:
    summary = github_service.stats_summary(session)
    summary["configured"] = token_configured()
    return summary


@router.post("/sync")
def start_sync(request: Request, runner=Depends(get_task_runner), session=Depends(get_session)) -> dict:
    """提交 GitHub 同步任务（同 kind 409 防重）。Token 未配置给出明确提示。"""

    if not token_configured():
        raise DomainError(
            "未配置 GITHUB_TOKEN，请在 ~/.personal-hub/.env 中设置后重试",
            code="github_token_missing",
            status_code=400,
        )
    session_factory = request.app.state.session_factory

    def job(progress_cb):
        client = GithubClient()
        try:
            with session_factory() as job_session:
                return github_service.run_sync_job(job_session, client, progress_cb=progress_cb)
        finally:
            client.close()

    task = runner.submit(github_service.SYNC_KIND, {}, job)
    return {"task_id": task.id, "status": task.status}


@router.get("/contributions")
def contributions(
    year: int = Query(..., ge=MIN_YEAR),
    session=Depends(get_session),
) -> dict:
    current_year = datetime.now(github_contrib.SH_TZ).year
    if year > current_year:
        raise DomainError("不允许查询未来年份", code="future_year", status_code=422)
    return github_contrib.contributions_for_year(session, year)


@router.get("/contributions/{date}")
def contribution_detail(date: IsoDate, session=Depends(get_session)) -> dict:
    from datetime import date as date_cls

    parsed = date_cls.fromisoformat(date)
    return github_contrib.day_detail(session, parsed)
