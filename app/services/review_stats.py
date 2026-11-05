"""确定性周统计（阶段一）：所有数字由代码计算，不交给 LLM 猜测。

口径约定：
- 自然周 = 周一至周日；week_bounds 把任意日期归一化到所在周的周一/周日。
- 任务"归属周"看 task_date，"完成周"看 completed_at——两者是不同概念，
  完成时间缺省（NULL）的任务不参与完成周统计（不伪造）。
- "周末逾期"按周日快照口径：task_date <= 周日 且（未完成 或 完成时间晚于周日），
  即周日结束时仍挂着未办的任务；未被错误认定为"已延期执行"。
- 字符串日期/时间为 ISO 格式，字典序比较即时间序。

统计结果同时供三处使用：Agent 工具、建议生成的确定性上下文、
周报确认时的 facts 小节（取生成草稿时的快照 stats_json）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Book, BookNote, DailyTask, ImportantInfo, LongTermPlan, Memo
from ..models.plan import TASK_TYPES, TASK_TYPE_LABELS

# 备忘"长期搁置"阈值：更新日期早于本周开始前该天数即标记
STALE_MEMO_DAYS = 14

# 统计中明细列表的条目上限（超出只给计数，防止统计体积极端膨胀）
LIST_CAP = 50


def _parse(day: str | date) -> date:
    if isinstance(day, date):
        return day
    return datetime.strptime(day, "%Y-%m-%d").date()


def week_bounds(day: str | date) -> tuple[str, str]:
    """任意日期归一化到所在自然周，返回 (周一, 周日)。"""
    d = _parse(day)
    start = d - timedelta(days=d.weekday())
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


def default_review_week(today: date | None = None) -> str:
    """默认回顾周期：上一个完整自然周的周一（本周周日结束后，本周才算完整）。"""
    t = today or date.today()
    monday = t - timedelta(days=t.weekday())
    if t >= monday + timedelta(days=7):
        return monday.isoformat()
    return (monday - timedelta(days=7)).isoformat()


def _cap(items: list, limit: int = LIST_CAP) -> dict:
    """明细列表封顶：超出部分只保留计数。"""
    if len(items) <= limit:
        return {"items": items, "total": len(items), "truncated": False}
    return {"items": items[:limit], "total": len(items), "truncated": True}


def _task_brief(task: DailyTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "task_date": task.task_date,
        "task_type": task.task_type,
        "task_type_label": TASK_TYPE_LABELS.get(task.task_type, task.task_type),
        "is_important": bool(task.is_important),
        "done": bool(task.done),
        "completed_at": task.completed_at,
        "moved_from_date": task.moved_from_date,
    }


def weekly_task_stats(session: Session, week_start: str) -> dict:
    start, end = week_bounds(week_start)
    start_ts, end_ts = f"{start}T00:00:00", f"{end}T23:59:59"

    # 归属本周的任务
    week_tasks = session.execute(
        select(DailyTask).where(DailyTask.task_date >= start, DailyTask.task_date <= end)
    ).scalars().all()
    # 本周内标记完成（无论归属哪天）
    done_in_week = session.execute(
        select(DailyTask).where(
            DailyTask.completed_at.is_not(None),
            DailyTask.completed_at >= start_ts,
            DailyTask.completed_at <= end_ts,
        )
    ).scalars().all()
    created_in_week = session.execute(
        select(func.count()).select_from(DailyTask).where(
            DailyTask.created_at >= start_ts, DailyTask.created_at <= end_ts
        )
    ).scalar_one()
    # 周末快照口径的逾期：周日结束时仍未办完（含历史积压，无下限）
    overdue = session.execute(
        select(DailyTask).where(DailyTask.task_date <= end).where(
            (DailyTask.done == 0)
            | ((DailyTask.completed_at.is_not(None)) & (DailyTask.completed_at > end_ts))
        )
    ).scalars().all()

    by_type = {task_type: {"total": 0, "done": 0} for task_type in TASK_TYPES}
    important_done = important_total = 0
    for task in week_tasks:
        bucket = by_type.setdefault(task.task_type, {"total": 0, "done": 0})
        bucket["total"] += 1
        bucket["done"] += 1 if task.done else 0
        if task.is_important:
            important_total += 1
            important_done += 1 if task.done else 0

    carried_done = [t for t in done_in_week if t.task_date < start]  # 存量任务本周被清掉
    return {
        "week_start": start,
        "week_end": end,
        "belonging": {
            "total": len(week_tasks),
            "done": sum(1 for t in week_tasks if t.done),
            "by_type": by_type,
            "important": {"total": important_total, "done": important_done},
        },
        "done_in_week": {
            "total": len(done_in_week),
            "belonging_to_week": sum(1 for t in done_in_week if start <= t.task_date <= end),
            "carried_in_done": _cap([_task_brief(t) for t in carried_done]),
        },
        "created_in_week": created_in_week,
        "overdue_at_week_end": _cap([_task_brief(t) for t in overdue]),
    }


def weekly_plan_snapshot(session: Session, week_start: str) -> dict:
    start, end = week_bounds(week_start)
    start_ts, end_ts = f"{start}T00:00:00", f"{end}T23:59:59"

    active = session.execute(
        select(LongTermPlan).where(LongTermPlan.status != "completed")
    ).scalars().all()
    completed_in_week = session.execute(
        select(LongTermPlan).where(
            LongTermPlan.completed_at.is_not(None),
            LongTermPlan.completed_at >= start_ts,
            LongTermPlan.completed_at <= end_ts,
        )
    ).scalars().all()

    def _brief(plan: LongTermPlan) -> dict:
        return {
            "id": plan.id,
            "title": plan.title,
            "goal": plan.goal,
            "status": plan.status,
            "target_date": plan.target_date,
            "is_important": bool(plan.is_important),
        }

    return {
        "active": _cap([_brief(p) for p in active]),
        "completed_in_week": [
            {**_brief(p), "completed_at": p.completed_at} for p in completed_in_week
        ],
        # 目标日期落在本周内的活动计划（临近到期信号）
        "target_date_in_week": [
            _brief(p) for p in active if p.target_date and start <= p.target_date <= end
        ],
    }


def memo_snapshot(session: Session, week_start: str) -> dict:
    start, _ = week_bounds(week_start)
    stale_before = (_parse(start) - timedelta(days=STALE_MEMO_DAYS)).isoformat()
    rows = session.execute(select(Memo).order_by(Memo.sort_order, Memo.id)).scalars().all()
    items = []
    stale_count = 0
    for memo in rows:
        updated_day = (memo.updated_at or "")[:10]
        stale = bool(updated_day) and updated_day < stale_before
        stale_count += 1 if stale else 0
        items.append(
            {
                "id": memo.id,
                "title": memo.title,
                "created_at": memo.created_at,
                "updated_at": memo.updated_at,
                "stale": stale,
            }
        )
    return {"total": len(rows), "stale": stale_count, "items": _cap(items)}


def important_info_snapshot(session: Session) -> dict:
    rows = session.execute(select(ImportantInfo).order_by(ImportantInfo.sort_order, ImportantInfo.id)).scalars().all()
    return {"total": len(rows), "titles": [row.title for row in rows]}


def reading_snapshot(session: Session, week_start: str) -> dict:
    start, end = week_bounds(week_start)
    start_ts, end_ts = f"{start}T00:00:00", f"{end}T23:59:59"

    books = session.execute(select(Book)).scalars().all()
    note_counts = dict(
        session.execute(
            select(BookNote.book_id, func.count()).group_by(BookNote.book_id)
        ).all()
    )
    by_status: dict[str, int] = {}
    for book in books:
        by_status[book.status] = by_status.get(book.status, 0) + 1

    def _brief(book: Book) -> dict:
        return {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "status": book.status,
            "is_important": bool(book.is_important),
            "note_count": note_counts.get(book.id, 0),
            "updated_at": book.updated_at,
        }

    notes_in_week = session.execute(
        select(func.count()).select_from(BookNote).where(
            BookNote.created_at >= start_ts, BookNote.created_at <= end_ts
        )
    ).scalar_one()
    return {
        "total": len(books),
        "by_status": by_status,
        "reading": [_brief(b) for b in books if b.status == "reading"],
        "updated_in_week": [_brief(b) for b in books if (b.updated_at or "")[:10] and start <= (b.updated_at or "")[:10] <= end],
        "notes_added_in_week": notes_in_week,
    }


def weekly_stats(session: Session, week_start: str) -> dict:
    """指定自然周的完整确定性统计（建议生成与周报 facts 的唯一事实来源）。"""
    start, end = week_bounds(week_start)
    return {
        "week_start": start,
        "week_end": end,
        "tasks": weekly_task_stats(session, start),
        "plans": weekly_plan_snapshot(session, start),
        "memos": memo_snapshot(session, start),
        "important_infos": important_info_snapshot(session),
        "reading": reading_snapshot(session, start),
    }
