"""每日任务业务逻辑（PRD §2.3 + 重要置顶/历史视图/逾期排序优化）：含 move 与排序语义。

排序规则（与长期计划一致）：重要状态 > 手动排序顺序（sort_order）。
某日视图 = 当日任务 + 更早日期未完成任务（逾期延续显示），两个分区内部均可手动排序
（scope=today / overdue）。完成时记录 completed_at；取消完成清空 completed_at。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..exceptions import DomainError, NotFoundError
from ..models import DailyTask


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def task_to_dict(task: DailyTask) -> dict:
    return {
        "id": task.id,
        "plan_id": task.plan_id,
        "task_date": task.task_date,
        "title": task.title,
        "done": bool(task.done),
        "sort_order": task.sort_order,
        "is_important": bool(task.is_important),
        "completed_at": task.completed_at,
        "moved_from_date": task.moved_from_date,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def list_daily(session: Session, task_date: str) -> list[dict]:
    """某日任务视图：当日任务 + 更早日期未完成的任务（逾期延续显示，PRD §2.3）。

    已完成的任务只在其归属日期显示，之后日期不再出现。
    整体按（重要 > sort_order > id）排序；前端按分区（逾期/今日）切分后
    各分区内部顺序与本结果一致。
    """

    rows = session.execute(
        select(DailyTask)
        .where(DailyTask.task_date <= task_date)
        .where(or_(DailyTask.task_date == task_date, DailyTask.done == 0))
        .order_by(DailyTask.is_important.desc(), DailyTask.sort_order, DailyTask.id)
    ).scalars().all()
    return [task_to_dict(row) for row in rows]


def list_task_history(session: Session, task_date: str | None = None) -> list[dict]:
    """已完成任务历史：按完成时间倒序（未知排最后），可按归属日期筛选。

    历史与当前任务共用 daily_tasks 表（done=1），不复制第二份数据。
    """

    statement = select(DailyTask).where(DailyTask.done == 1)
    if task_date:
        statement = statement.where(DailyTask.task_date == task_date)
    completed_unknown = DailyTask.completed_at.is_(None)
    statement = statement.order_by(completed_unknown, DailyTask.completed_at.desc(), DailyTask.id.desc())
    rows = session.execute(statement).scalars().all()
    return [task_to_dict(row) for row in rows]


def create_task(
    session: Session,
    *,
    task_date: str,
    title: str,
    plan_id: int | None = None,
    is_important: bool = False,
) -> dict:
    max_order = session.execute(
        select(DailyTask.sort_order).where(DailyTask.task_date == task_date).order_by(DailyTask.sort_order.desc())
    ).scalars().first()
    task = DailyTask(
        task_date=task_date,
        title=title,
        plan_id=plan_id,
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
    if "done" in fields and fields["done"] is not None:
        done = 1 if fields["done"] else 0
        if done != task.done:
            # 完成/取消完成同步维护完成时间（取消完成即离开历史视图）
            task.completed_at = _now() if done else None
        task.done = done
    if "plan_id" in fields:
        task.plan_id = fields["plan_id"]
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


def reorder_tasks(session: Session, task_date: str, ordered_ids: list[int], scope: str = "today") -> list[dict]:
    """按 ordered_ids 重排某日视图的指定分区；任何 id 不属于该分区则整体拒绝（409）。

    scope=today：task_date == date 的任务（原有语义）；
    scope=overdue：更早日期未完成的任务（逾期分区，同样支持手动排序）。
    仅写 sort_order，不修改任务日期、完成状态等其他内容。
    """

    statement = select(DailyTask)
    if scope == "overdue":
        statement = statement.where(DailyTask.task_date < task_date, DailyTask.done == 0)
    else:
        statement = statement.where(DailyTask.task_date == task_date)
    rows = session.execute(statement).scalars().all()
    by_id = {row.id: row for row in rows}
    if len(ordered_ids) != len(by_id) or any(task_id not in by_id for task_id in ordered_ids):
        label = "更早日期未完成任务" if scope == "overdue" else task_date
        raise DomainError(
            f"排序列表与 {label} 的任务不一致",
            code="reorder_mismatch",
            status_code=409,
        )
    for index, task_id in enumerate(ordered_ids):
        by_id[task_id].sort_order = index + 1
    session.commit()
    return list_daily(session, task_date)
