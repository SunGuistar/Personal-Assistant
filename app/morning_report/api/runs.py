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
