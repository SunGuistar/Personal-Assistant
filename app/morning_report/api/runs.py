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
    def fn(session, run_id):
        return news_pipeline.run_collect(session, run_id, cancel_token=runner.token_for(run_id))

    if not runner.submit("collect", run.id, fn):
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
        token = request.app.state.mr_runner.token_for(run_id)
        report_service.run_generate(
            session, run_id, settings, mode="auto" if mode == "auto" else "manual",
            hub_session_factory=request.app.state.session_factory,
            mr_session_factory=request.app.state.mr_session_factory,
            clear_cache=True if mode == "full" else None,
            cancel_token=token,
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
        "event_group_id": r.event_group_id, "is_important": bool(r.is_important),
    } for r in rows]
    return {"run_id": run_id, "status": run.status, "count": len(items), "items": items}


@router.post("/{run_id}/stop")
def stop_run(run_id: int, request: Request, mr: Session = Depends(get_mr_session)) -> dict:
    """协作式停止指定 Run：置 stopping + 取消令牌；节点在安全检查点停止。

    幂等：已终态/已在停止中直接返回当前状态；与任务自然完成的竞态由状态守卫处理。
    """
    from ...exceptions import NotFoundError
    from ..services.cancel import CancelToken  # noqa: F401
    from ..services.progress import ACTIVE_RUN_STATUS, TERMINAL_RUN_STATUS

    run = mr.get(RunRecord, run_id)
    if run is None:
        raise NotFoundError("运行记录不存在")
    if run.status in TERMINAL_RUN_STATUS:
        return {"run_id": run_id, "status": run.status, "note": "任务已终态，无需停止"}
    if run.status == "stopping":
        return {"run_id": run_id, "status": "stopping", "note": "已在停止中"}

    # 状态守卫：只有仍处于活动态才允许改成 stopping（防与自然完成竞态）
    from sqlalchemy import update as sa_update
    res = mr.execute(
        sa_update(RunRecord)
        .where(RunRecord.id == run_id, RunRecord.status.in_(ACTIVE_RUN_STATUS))
        .values(status="stopping", stop_reason="用户主动停止")
    )
    mr.commit()
    if res.rowcount == 0:
        # 期间已自然完成
        mr.refresh(run)
        return {"run_id": run_id, "status": run.status, "note": "任务已自然完成"}

    running = mr.execute(
        select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.id.desc()).limit(1)
    ).scalars().first()
    mr.add(RunLog(
        run_id=run_id, stage="stop", level="warning",
        message="收到停止请求（用户主动停止）",
        detail={"stage_at_request": running.stage if running else None},
    ))
    mr.commit()
    request.app.state.mr_runner.request_cancel(run_id)
    return {"run_id": run_id, "status": "stopping"}
