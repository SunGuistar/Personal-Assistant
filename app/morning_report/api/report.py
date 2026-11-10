"""报告查询、质量评价、重新生成与用量统计。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...exceptions import NotFoundError
from ..models import Evaluation, ReportVersion, RunRecord, TokenUsage
from .deps import get_mr_session

router = APIRouter()


def _version_out(v: ReportVersion, ev: Evaluation | None) -> dict:
    return {
        "id": v.id, "report_date": v.report_date, "version_no": v.version_no,
        "is_primary": v.is_primary, "status": v.status, "title": v.title,
        "sections": v.sections, "content_md": v.content_md,
        "window_start": v.window_start, "window_end": v.window_end,
        "snapshot_id": v.snapshot_id, "fact_check": v.fact_check,
        "generation_mode": v.generation_mode, "created_at": v.created_at,
        "evaluation": None if ev is None else {
            "status": ev.status, "scores": ev.scores, "composite": ev.composite,
            "comment": ev.comment, "rule_version": ev.rule_version,
        },
    }


@router.get("/report")
def get_report(
    report_date: str | None = None,
    version_no: int | None = None,
    mr: Session = Depends(get_mr_session),
) -> dict:
    """默认取当日主报告；传 version_no 取指定版本；均无则 404。"""
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    date = report_date or today
    q = select(ReportVersion).where(ReportVersion.report_date == date)
    if version_no is not None:
        q = q.where(ReportVersion.version_no == version_no)
    else:
        q = q.where(ReportVersion.is_primary.is_(True))
    v = mr.execute(q.order_by(ReportVersion.id.desc()).limit(1)).scalars().first()
    if v is None:
        raise NotFoundError("报告不存在")
    ev = mr.execute(
        select(Evaluation).where(Evaluation.version_id == v.id).order_by(Evaluation.id.desc())
    ).scalars().first()
    return _version_out(v, ev)


@router.get("/history")
def history(mr: Session = Depends(get_mr_session)) -> dict:
    rows = mr.execute(
        select(ReportVersion).order_by(ReportVersion.report_date.desc(), ReportVersion.version_no.desc())
    ).scalars().all()
    return {"items": [{
        "id": v.id, "report_date": v.report_date, "version_no": v.version_no,
        "is_primary": v.is_primary, "status": v.status, "created_at": v.created_at,
        "has_evaluation": mr.execute(
            select(Evaluation.id).where(Evaluation.version_id == v.id).limit(1)).first() is not None,
    } for v in rows]}


class RegenerateIn(BaseModel):
    report_date: str | None = None
    mode: str = "reuse"  # reuse=复用缓存局部重算；full=完整重算


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
            clear_cache=body.mode == "full",
        )

    if not request.app.state.mr_runner.submit("generate", run.id, fn):
        mr.delete(run)
        mr.commit()
        from ...exceptions import DomainError
        raise DomainError("已有一期生成在进行中，请勿重复提交", code="task_conflict", status_code=409)
    return {"run_id": run.id, "mode": body.mode, "status": "pending"}


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
