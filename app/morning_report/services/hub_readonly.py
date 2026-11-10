"""hub.db（现有个人助手库）只读访问：为“我的昨日”和目标分析提供证据。

铁律：本模块只做 SELECT；不创建、不修改、不删除 hub 的任何数据。
所有函数接收调用方提供的只读意图 session（hub session_factory 产物）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import DailyTask, ImportantInfo, LongTermPlan


@dataclass
class PersonalContext:
    """当期个人上下文（窗口内证据 + 权威长期计划）。"""

    window_start: str
    window_end: str
    daily_done: list[dict] = field(default_factory=list)  # 窗口内完成的任务
    daily_pending: list[dict] = field(default_factory=list)
    longterm_highlight: list[dict] = field(default_factory=list)  # 标红重要计划
    longterm_active: list[dict] = field(default_factory=list)
    important_infos: list[dict] = field(default_factory=list)


def _in_window(ts: str | None, start: str, end: str) -> bool:
    if not ts:
        return False
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return start <= t.isoformat() < end


def load_personal_context(hub: Session, window_start: str, window_end: str) -> PersonalContext:
    """读取窗口内每日任务完成证据与长期计划（标红优先）。

    只使用带 completed_at 时间证据的记录（V0.6 §4.2：不把当前状态推断为昨日完成）。
    """

    ctx = PersonalContext(window_start=window_start, window_end=window_end)

    tasks = hub.execute(select(DailyTask)).scalars().all()
    for t in tasks:
        rec = {
            "id": t.id,
            "task_date": t.task_date,
            "title": t.title,
            "task_type": t.task_type,
            "is_important": bool(t.is_important),
            "completed_at": t.completed_at,
        }
        if t.done and _in_window(t.completed_at, window_start, window_end):
            ctx.daily_done.append(rec)
        elif not t.done and t.task_date >= window_end[:10]:
            ctx.daily_pending.append(rec)

    plans = hub.execute(select(LongTermPlan)).scalars().all()
    for p in plans:
        rec = {
            "id": p.id,
            "title": p.title,
            "description": p.description,
            "goal": p.goal,
            "status": p.status,
            "target_date": p.target_date,
        }
        if p.is_important and p.status != "completed":
            ctx.longterm_highlight.append(rec)
        elif p.status == "in_progress":
            ctx.longterm_active.append(rec)

    infos = hub.execute(select(ImportantInfo).order_by(ImportantInfo.sort_order)).scalars().all()
    ctx.important_infos = [{"id": i.id, "title": i.title, "content": i.content} for i in infos]
    return ctx


def window_for(report_date: str) -> tuple[str, str]:
    """report_date（北京时间自然日）对应的内容窗口 [前一天08:00, 当天08:00)。"""

    day = datetime.fromisoformat(report_date).date()
    start = datetime(day.year, day.month, day.day, 8, 0) - timedelta(days=1)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()
