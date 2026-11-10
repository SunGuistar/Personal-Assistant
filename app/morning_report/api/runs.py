"""采集运行接口：手动触发采集、查询新闻明细与运行日志。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...exceptions import DomainError, NotFoundError
from ..models import NewsItem, RunLog, RunRecord
from ..schemas import LogOut
from ..services import news_pipeline
from .deps import get_mr_session

router = APIRouter(prefix="/runs")


@router.post("/collect", status_code=202)
def trigger_collect(
    request: Request,
    report_date: str | None = None,
    mr: Session = Depends(get_mr_session),
) -> dict:
    date = report_date or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    run = news_pipeline.create_collect_run(mr, date)
    runner = request.app.state.mr_runner
    if not runner.submit("collect", run.id, news_pipeline.run_collect):
        mr.delete(run)
        mr.commit()
        raise DomainError("已有一期采集在进行中，请勿重复提交", code="task_conflict", status_code=409)
    return {"run_id": run.id, "run_date": date, "status": "pending"}


@router.post("/generate", status_code=202)
def trigger_generate(
    request: Request,
    report_date: str | None = None,
    mode: str = "manual",
    mr: Session = Depends(get_mr_session),
) -> dict:
    """手动重新生成：默认复用缓存/局部重算；mode=full 完整重算。正式模型时段外将失败。"""
    from ..models import RunRecord
    from ..services import report_service

    date = report_date or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    run = RunRecord(run_date=date, kind="generate", status="pending")
    mr.add(run)
    mr.commit()
    settings = request.app.state.mr_settings

    def fn(session, run_id):
        report_service.run_generate(
            session, run_id, settings, mode="auto" if mode == "auto" else "manual",
            hub_session_factory=request.app.state.session_factory,
            mr_session_factory=request.app.state.mr_session_factory,
        )

    if not request.app.state.mr_runner.submit("generate", run.id, fn):
        mr.delete(run)
        mr.commit()
        raise DomainError("已有一期生成在进行中，请勿重复提交", code="task_conflict", status_code=409)
    return {"run_id": run.id, "run_date": date, "status": "pending"}


@router.get("/{run_id}/logs", response_model=list[LogOut])
def run_logs(run_id: int, mr: Session = Depends(get_mr_session)) -> list[LogOut]:
    if mr.get(RunRecord, run_id) is None:
        raise NotFoundError("运行记录不存在")
    rows = mr.execute(
        select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.id)
    ).scalars().all()
    return [LogOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/{run_id}/news")
def run_news(run_id: int, mr: Session = Depends(get_mr_session)) -> dict:
    run = mr.get(RunRecord, run_id)
    if run is None:
        raise NotFoundError("运行记录不存在")
    rows = mr.execute(select(NewsItem).where(NewsItem.run_id == run_id)).scalars().all()
    items = [{
        "id": r.id, "category": r.category, "title": r.title, "summary": r.summary,
        "source_name": r.source_name, "source_url": r.source_url, "published_at": r.published_at,
        "event_group_id": r.event_group_id,
    } for r in rows]
    return {"run_id": run_id, "status": run.status, "count": len(items), "items": items}
