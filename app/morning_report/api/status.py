"""模块状态与健康：DB 迁移状态、当日运行、窗口内新闻计数、hub 只读上下文预览。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import NewsItem, RunRecord
from ..db import current_version
from ..config import MRSettings
from ..schemas import PersonalContextOut, RunOut, StatusOut
from ..services import hub_readonly
from .deps import get_hub_session, get_mr_session, get_mr_settings

router = APIRouter()


def _today_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


@router.get("/status", response_model=StatusOut)
def get_status(
    mr: Session = Depends(get_mr_session),
    settings: MRSettings = Depends(get_mr_settings),
) -> StatusOut:
    today = _today_cst()
    run = mr.execute(
        select(RunRecord)
        .where(RunRecord.run_date == today, RunRecord.kind == "generate")
        .order_by(RunRecord.id.desc())
    ).scalars().first()
    counts = dict(
        mr.execute(
            select(NewsItem.category, func.count())
            .where(NewsItem.run_id.in_(
                select(RunRecord.id).where(RunRecord.run_date == today, RunRecord.kind == "collect")
            ))
            .group_by(NewsItem.category)
        ).all()
    )
    return StatusOut(
        db_ok=True,
        mr_schema_version=current_version(mr.get_bind()),
        schedule_enabled=settings.schedule_enabled,
        today=today,
        today_run={
            "id": run.id, "status": run.status, "error": run.error,
            "started_at": run.started_at, "finished_at": run.finished_at,
        } if run else None,
        news_counts={k: counts.get(k, 0) for k in ("domestic", "international", "ai")},
    )


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    limit: int = 14,
    mr: Session = Depends(get_mr_session),
) -> list[RunOut]:
    rows = mr.execute(
        select(RunRecord).order_by(RunRecord.id.desc()).limit(min(limit, 100))
    ).scalars().all()
    return [RunOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/personal_context", response_model=PersonalContextOut)
def personal_context(
    report_date: str | None = None,
    hub: Session = Depends(get_hub_session),
) -> PersonalContextOut:
    date = report_date or _today_cst()
    start, end = hub_readonly.window_for(date)
    ctx = hub_readonly.load_personal_context(hub, start, end)
    return PersonalContextOut(**ctx.__dict__)
