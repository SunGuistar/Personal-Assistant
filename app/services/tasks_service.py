"""每日任务业务逻辑：统一排序（未完成优先 > 重要 > 类型 > 手动）、取消完成、类型分组。

某日视图 = 当日任务 + 更早日期未完成任务（逾期延续显示），统一排序规则：

    未完成优先 > 重要状态 > 任务类型(日常/功能添加/功能优化/奇思妙想) > 手动 sort_order

- 已完成任务整体置底（重要已完成同样置底），内部按完成时间倒序（未知最后）稳定展示；
- 完成/取消完成可反复切换：完成记 completed_at，取消完成清除并回到未完成区；
- 手动排序仅限同一分组（未完成|重要状态|任务类型 相同）内部，越界 409；
- 排序只改 sort_order，不改任务日期/重要状态/类型。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
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
    """某日视图可见任务：当日全部 + 更早日期未完成。"""

    return (
        select(DailyTask)
        .where(DailyTask.task_date <= task_date)
        .where(or_(DailyTask.task_date == task_date, DailyTask.done == 0))
    )


def _group_key(task: DailyTask) -> tuple:
    """手动排序分组键：跨（完成状态|重要|类型）边界不允许普通上下移。"""

    return (bool(task.done), bool(task.is_important), task.task_type)


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
        .where(DailyTask.task_date <= task_date)
        .where(or_(DailyTask.task_date == task_date, DailyTask.done == 0))
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


def move_task(session: Session, task_id: int, target_date: str) -> dict:
    """移至某天：task_date 变更并记录来源；不复制副本。"""

    task = get_task(session, task_id)
    if task.task_date != target_date:
        task.moved_from_date = task.task_date
        task.task_date = target_date
        max_order = session.execute(
            select(DailyTask.sort_order)
            .where(DailyTask.task_date == target_date)
            .order_by(DailyTask.sort_order.desc())
        ).scalars().first()
        task.sort_order = (max_order or 0) + 1
        session.commit()
        session.refresh(task)
    return task_to_dict(task)


def reorder_tasks(session: Session, task_date: str, ordered_ids: list[int]) -> list[dict]:
    """统一待办重排：ordered_ids 须与该日期视图全部可见任务完全一致（409 兜底），
    且各分组（完成状态|重要|类型）的相对顺序不得改变——普通上下移只能在
    同组内部进行，不能跨越重要/类型/完成边界。
    """

    rows = list(session.execute(_visible_statement(task_date)).scalars().all())
    by_id = {row.id: row for row in rows}
    if len(ordered_ids) != len(by_id) or any(task_id not in by_id for task_id in ordered_ids):
        raise DomainError(
            f"排序列表与 {task_date} 待办视图的任务不一致",
            code="reorder_mismatch",
            status_code=409,
        )
    current_keys = [_group_key(row) for row in _sort_display(rows)]
    submitted_keys = [_group_key(by_id[task_id]) for task_id in ordered_ids]
    if current_keys != submitted_keys:
        raise DomainError(
            "排序不能跨越 完成状态 / 重要 / 任务类型 分组边界",
            code="reorder_cross_group",
            status_code=409,
        )
    for index, task_id in enumerate(ordered_ids):
        by_id[task_id].sort_order = index + 1
    session.commit()
    return list_daily(session, task_date)
