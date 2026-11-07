"""每日任务业务逻辑：统一排序（未完成优先 > 重要 > 类型 > 创建先后）、取消完成、类型分组。

某日视图 = 当日任务 + 更早日期未完成任务（逾期延续显示），统一排序规则：

    未完成优先 > 重要状态 > 任务类型(日常/功能添加/功能优化/奇思妙想) > sort_order

- 已完成任务整体置底（重要已完成同样置底），内部按完成时间倒序（未知最后）稳定展示；
- 完成/取消完成可反复切换：完成记 completed_at，取消完成清除并回到未完成区；
- 无手动排序入口：sort_order 仅由创建追加（max+1）决定同组内先后顺序。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..exceptions import DomainError, NotFoundError
from ..models import DailyTask
from ..models.plan import TASK_TYPES, _TYPE_INDEX


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def task_to_dict(task: DailyTask) -> dict:
    return {
        "id": task.id,
        "task_date": task.task_date,
        "title": task.title,
        "content": task.content,
        "task_type": task.task_type,
        "done": bool(task.done),
        "sort_order": task.sort_order,
        "is_important": bool(task.is_important),
        "completed_at": task.completed_at,
        "moved_from_date": task.moved_from_date,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _visible_statement(task_date: str):
    """某日视图可见任务：当日全部 + 更早日期未完成 + 更早日期但本日完成的任务。

    逾期任务在别的日期勾选完成后，完成动作发生在视图日——继续在该视图置底展示
    （避免"勾完就消失"），同时仍可在其归属日期视图看到；完成时间不存在的
    历史脏数据退回"仅归属日期"口径。
    """

    return (
        select(DailyTask)
        .where(DailyTask.task_date <= task_date)
        .where(
            or_(
                DailyTask.task_date == task_date,
                DailyTask.done == 0,
                func.date(DailyTask.completed_at) == task_date,
            )
        )
    )


def _sort_display(rows: list[DailyTask]) -> list[DailyTask]:
    """统一排序：未完成优先 > 重要 > 类型顺序 > sort_order > id；
    已完成置底（重要已完成同样置底），内部按完成时间倒序（未知最后）+ id 倒序。"""

    unfinished = [row for row in rows if not row.done]
    finished = [row for row in rows if row.done]
    unfinished.sort(key=lambda t: (-t.is_important, _TYPE_INDEX.get(t.task_type, 99), t.sort_order, t.id))
    finished_known = sorted(
        [t for t in finished if t.completed_at is not None],
        key=lambda t: (t.completed_at, t.id),
        reverse=True,
    )
    finished_unknown = sorted([t for t in finished if t.completed_at is None], key=lambda t: -t.id)
    return unfinished + finished_known + finished_unknown


def list_daily(session: Session, task_date: str) -> list[dict]:
    """按统一排序返回某日视图；前端直接按此顺序展示。"""

    rows = session.execute(_visible_statement(task_date).order_by(DailyTask.id)).scalars().all()
    return [task_to_dict(row) for row in _sort_display(list(rows))]


def list_task_history(session: Session, task_date: str | None = None) -> list[dict]:
    """已完成任务历史：按完成时间倒序（未知排最后），可按归属日期筛选。"""

    statement = select(DailyTask).where(DailyTask.done == 1)
    if task_date:
        statement = statement.where(DailyTask.task_date == task_date)
    rows = session.execute(statement).scalars().all()
    ordered = sorted(
        [t for t in rows if t.completed_at is not None],
        key=lambda t: (t.completed_at, t.id),
        reverse=True,
    ) + sorted([t for t in rows if t.completed_at is None], key=lambda t: -t.id)
    return [task_to_dict(row) for row in ordered]


def _validate_task_type(task_type: str) -> None:
    if task_type not in TASK_TYPES:
        raise DomainError(
            f"非法任务类型: {task_type}（仅支持 {', '.join(TASK_TYPES)}）",
            code="invalid_task_type",
            status_code=400,
        )


def create_task(
    session: Session,
    *,
    task_date: str,
    title: str,
    content: str | None = None,
    task_type: str = "daily",
    is_important: bool = False,
) -> dict:
    _validate_task_type(task_type)
    # 追加到该日期视图末尾（max sort_order + 1）；排序键自动归位
    max_order = session.execute(
        select(DailyTask.sort_order)
        .where(DailyTask.id.in_(_visible_statement(task_date).with_only_columns(DailyTask.id)))
        .order_by(DailyTask.sort_order.desc())
    ).scalars().first()
    task = DailyTask(
        task_date=task_date,
        title=title,
        content=content or None,
        task_type=task_type,
        is_important=1 if is_important else 0,
        sort_order=(max_order or 0) + 1,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task_to_dict(task)


def get_task(session: Session, task_id: int) -> DailyTask:
    task = session.get(DailyTask, task_id)
    if task is None:
        raise NotFoundError(f"任务不存在: {task_id}")
    return task


def update_task(session: Session, task_id: int, fields: dict) -> dict:
    task = get_task(session, task_id)
    if "title" in fields and fields["title"] is not None:
        task.title = fields["title"]
    if "content" in fields:
        task.content = fields["content"] or None
    if "task_type" in fields and fields["task_type"] is not None:
        _validate_task_type(fields["task_type"])
        task.task_type = fields["task_type"]
    if "done" in fields and fields["done"] is not None:
        done = 1 if fields["done"] else 0
        if done != task.done:
            # 完成 → 记完成时间；取消完成 → 清除完成时间并回到未完成区（可反复切换）
            task.completed_at = _now() if done else None
        task.done = done
    if fields.get("is_important") is not None:
        task.is_important = 1 if fields["is_important"] else 0
    session.commit()
    session.refresh(task)
    return task_to_dict(task)


def delete_task(session: Session, task_id: int) -> None:
    task = get_task(session, task_id)
    session.delete(task)
    session.commit()
