"""报告查询、重新生成与用量统计。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...exceptions import NotFoundError
from ..models import ReportVersion, RunRecord, TokenUsage
from .deps import get_mr_session

router = APIRouter()


def _version_out(v: ReportVersion, mr: Session) -> dict:
    from ..services.report_news_content import display_sections
    from ..services.report_assembly import display_yesterday
    return {
        "id": v.id, "report_date": v.report_date, "version_no": v.version_no,
        "is_primary": v.is_primary, "status": v.status, "title": v.title,
        "sections": display_yesterday(mr, v, display_sections(mr, v)), "content_md": v.content_md,
        "window_start": v.window_start, "window_end": v.window_end,
        "snapshot_id": v.snapshot_id,
        "generation_mode": v.generation_mode, "created_at": v.created_at,

    }


@router.get("/report")
def get_report(
    report_date: str | None = None,
    version_no: int | None = None,
    mr: Session = Depends(get_mr_session),
) -> dict | None:
    """默认无已发布晨报时返回正常空状态；显式日期/版本不存在仍返回404。"""
    q = select(ReportVersion).where(ReportVersion.status == "published")
    if report_date is not None:
        q = q.where(ReportVersion.report_date == report_date)
    if version_no is not None:
        q = q.where(ReportVersion.version_no == version_no)
    v = mr.execute(q.order_by(ReportVersion.report_date.desc(), ReportVersion.id.desc()).limit(1)).scalars().first()
    if v is None:
        if report_date is None and version_no is None:
            return None
        raise NotFoundError("报告不存在")
    return _version_out(v, mr)


@router.get("/history")
def history(mr: Session = Depends(get_mr_session)) -> dict:
    from ..services.report_actions import latest_per_day
    rows = latest_per_day(mr)
    return {"items": [{
        "id": v.id, "report_date": v.report_date, "version_no": v.version_no,
        "is_primary": v.is_primary, "status": v.status, "created_at": v.created_at,

    } for v in rows]}


class RegenerateIn(BaseModel):
    report_date: str | None = None
    mode: str = "reuse"  # 兼容旧客户端，统一重新生成，不再区分 full


@router.post("/regenerate", status_code=202)
def regenerate(body: RegenerateIn, request: Request, mr: Session = Depends(get_mr_session)) -> dict:
    """重新生成：旧版本全部保留，新成功结果为附加版本（除非当日尚无主报告）。"""
    from datetime import datetime, timedelta, timezone

    from ..models import RunRecord
    from ..services import report_service

    date = body.report_date or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    run = RunRecord(run_date=date, kind="generate", status="pending")
    mr.add(run)
    mr.commit()
    settings = request.app.state.mr_settings

    def fn(session, run_id):
        report_service.run_generate(
            session, run_id, settings, mode="manual",
            hub_session_factory=request.app.state.session_factory,
            mr_session_factory=request.app.state.mr_session_factory,
            clear_cache=False,
            cancel_token=request.app.state.mr_runner.token_for(run_id),
        )

    if not request.app.state.mr_runner.submit("generate", run.id, fn):
        mr.delete(run)
        mr.commit()
        from ...exceptions import DomainError
        raise DomainError("已有一期生成在进行中，请勿重复提交", code="task_conflict", status_code=409)
    return {"run_id": run.id, "mode": "reuse", "status": "pending"}


class ReassembleIn(BaseModel):
    version_id: int


@router.post("/reassemble", status_code=202)
def reassemble(body: ReassembleIn, request: Request, mr: Session = Depends(get_mr_session)) -> dict:
    from ..services.report_actions import assembly_state, run_reassemble
    source = mr.get(ReportVersion, body.version_id)
    if source is None or source.status != "published":
        raise NotFoundError("待组装的晨报不存在")
    assembly_state(mr, source)  # 提交前检查；禁止缺数据时偷偷重新采集或调用模型。
    run = RunRecord(run_date=source.report_date, kind="generate", status="pending")
    mr.add(run)
    mr.commit()

    def fn(session, run_id):
        return run_reassemble(session, run_id, body.version_id,
            mr_session_factory=request.app.state.mr_session_factory,
            cancel_token=request.app.state.mr_runner.token_for(run_id))

    if not request.app.state.mr_runner.submit("generate", run.id, fn):
        mr.delete(run)
        mr.commit()
        from ...exceptions import DomainError
        raise DomainError("已有晨报任务在进行中", code="task_conflict", status_code=409)
    return {"run_id": run.id, "status": "pending"}


@router.get("/usage")
def usage(run_id: int | None = None, mr: Session = Depends(get_mr_session)) -> dict:
    q = select(TokenUsage)
    if run_id is not None:
        q = q.where(TokenUsage.run_id == run_id)
    rows = mr.execute(q.order_by(TokenUsage.id)).scalars().all()
    items = [{
        "node": r.node, "provider": r.provider, "model": r.model,
        "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
        "cache_hit_tokens": r.cache_hit_tokens, "cache_miss_tokens": r.cache_miss_tokens,
        "elapsed_ms": r.elapsed_ms, "cost_usd": r.cost_usd, "price_tier": r.price_tier,
        "created_at": r.created_at,
    } for r in rows]
    totals = {
        "input_tokens": sum(i["input_tokens"] or 0 for i in items),
        "output_tokens": sum(i["output_tokens"] or 0 for i in items),
        "elapsed_ms": sum(i["elapsed_ms"] or 0 for i in items),
        "calls": len(items),
    }
    return {"items": items, "totals": totals}
