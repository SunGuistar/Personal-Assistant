"""每日任务业务逻辑（PRD §2.3）：含 move 与排序语义。"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..exceptions import DomainError, NotFoundError
from ..models import DailyTask


def task_to_dict(task: DailyTask) -> dict:
    return {
        "id": task.id,
        "plan_id": task.plan_id,
        "task_date": task.task_date,
        "title": task.title,
        "done": bool(task.done),
        "sort_order": task.sort_order,
        "moved_from_date": task.moved_from_date,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def list_daily(session: Session, task_date: str) -> list[dict]:
    rows = session.execute(
        select(DailyTask)
        .where(DailyTask.task_date == task_date)
        .order_by(DailyTask.sort_order, DailyTask.id)
    ).scalars().all()
    return [task_to_dict(row) for row in rows]


def create_task(
    session: Session, *, task_date: str, title: str, plan_id: int | None = None
) -> dict:
    max_order = session.execute(
        select(DailyTask.sort_order).where(DailyTask.task_date == task_date).order_by(DailyTask.sort_order.desc())
    ).scalars().first()
    task = DailyTask(
        task_date=task_date,
        title=title,
        plan_id=plan_id,
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
    if "done" in fields and fields["done"] is not None:
        task.done = 1 if fields["done"] else 0
    if "plan_id" in fields:
        task.plan_id = fields["plan_id"]
    session.commit()
    session.refresh(task)
    return task_to_dict(task)


def delete_task(session: Session, task_id: int) -> None:
    task = get_task(session, task_id)
    session.delete(task)
    session.commit()


def move_task(session: Session, task_id: int, target_date: str) -> dict:
    """移至某天：task_date 变更并记录来源；不复制副本（PRD 已确定语义）。"""

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
    """按 ordered_ids 重排某日任务；任何 id 不属于该日期则整体拒绝（409）。"""

    rows = session.execute(select(DailyTask).where(DailyTask.task_date == task_date)).scalars().all()
    by_id = {row.id: row for row in rows}
    if len(ordered_ids) != len(by_id) or any(task_id not in by_id for task_id in ordered_ids):
        raise DomainError(
            f"排序列表与 {task_date} 的任务不一致",
            code="reorder_mismatch",
            status_code=409,
        )
    for index, task_id in enumerate(ordered_ids):
        by_id[task_id].sort_order = index + 1
    session.commit()
    return list_daily(session, task_date)
