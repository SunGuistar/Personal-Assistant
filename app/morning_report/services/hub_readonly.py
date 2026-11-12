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


# 决策工作流：独立只读连接，绝不复用可写 hub Session。
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import hashlib
from datetime import timezone

CST = timezone(timedelta(hours=8))


@contextmanager
def readonly_connection(path):
    path = Path(path).resolve(strict=True)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        yield connection
    finally:
        connection.close()


def _stamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=CST) if parsed.tzinfo is None else parsed.astimezone(CST)
    except ValueError:
        return None


def load_readonly_context(path, window_start, window_end):
    """读取已明确配置的数据源；不存在或异常时上抛，不猜测其他库。"""
    path = Path(path).resolve(strict=True)
    start, end = _stamp(window_start), _stamp(window_end)
    tables = ("daily_tasks", "long_term_plans", "important_infos", "memos", "books", "book_notes")
    records, missing = {}, []
    with readonly_connection(path) as db:
        available = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in tables:
            if table not in available:
                missing.append(table)
                records[table] = []
                continue
            rows = [dict(row) for row in db.execute("SELECT * FROM " + table)]
            for row in rows:
                row["source_id"] = f"{table}:{row['id']}"
                row["recorded_at"] = row.get("completed_at") or row.get("updated_at") or row.get("created_at") or row.get("uploaded_at")
                # 附件只提供数据库已有元数据，不读取磁盘正文、不泄露附件路径。
                row.pop("path", None)
            records[table] = rows
    if "daily_tasks" in missing or "long_term_plans" in missing:
        raise ValueError("configured personal database lacks required tables")
    tasks = records["daily_tasks"]
    today, yesterday = end.date().isoformat(), start.date().isoformat()
    done = [r for r in tasks if r.get("done") and _stamp(r.get("completed_at")) is not None
            and start <= _stamp(r["completed_at"]) < end]
    pending = [r for r in tasks if not r.get("done") and r.get("task_date", "") <= today]
    plans = records["long_term_plans"]
    counts = {table: len(rows) for table, rows in records.items()}
    meta = {"source_id": hashlib.sha256(str(path).casefold().encode()).hexdigest()[:16],
            "database_path": str(path), "readonly": True,
            "queried_at": datetime.now(CST).isoformat(), "counts": counts,
            "missing_tables": missing, "query_error": None,
            "status": "empty" if not any(counts.values()) else "ok"}
    return {"window_start": window_start, "window_end": window_end,
        "daily_done": done, "daily_pending": pending,
        "yesterday_pending": [r for r in pending if r.get("task_date") == yesterday],
        "today_pending": [r for r in pending if r.get("task_date") == today],
        "longterm_highlight": [r for r in plans if r.get("is_important") and r.get("status") != "completed"],
        "longterm_active": [r for r in plans if r.get("status") == "in_progress" and not r.get("is_important")],
        "important_infos": records["important_infos"], "memos": records["memos"],
        "books": records["books"], "book_notes": records["book_notes"],
        "history_tasks": sorted([r for r in tasks if r.get("task_date", "") <= today],
                                key=lambda r: (r.get("task_date", ""), r["id"]), reverse=True)[:200],
        "source_meta": meta}
