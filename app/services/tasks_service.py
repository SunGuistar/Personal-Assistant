"""每日任务业务逻辑（PRD §2.3 + 综合优化轮）：统一排序、历史只读、与长期计划独立。

某日视图 = 当日任务 + 更早日期未完成任务（逾期延续显示），两类任务纳入**统一排序**：
排序键统一为（重要 > sort_order > id），今日任务与逾期任务可经上移/下移自由穿插；
排序只改 sort_order，不改任务所属日期与完成状态。已完成任务只在其归属日期显示。

历史只读：任务完成后进入历史（done=1 + completed_at），不允许恢复为未完成
（service 层 409 拦截，旧入口同样受限）。
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


def _visible_statement(task_date: str):
    """某日视图可见任务：当日全部 + 更早日期未完成。"""

    return (
        select(DailyTask)
        .where(DailyTask.task_date <= task_date)
        .where(or_(DailyTask.task_date == task_date, DailyTask.done == 0))
    )


def list_daily(session: Session, task_date: str) -> list[dict]:
    """按统一排序返回某日视图（重要 > sort_order > id）；前端直接按此顺序展示。"""

    rows = session.execute(
        _visible_statement(task_date).order_by(
            DailyTask.is_important.desc(), DailyTask.sort_order, DailyTask.id
        )
    ).scalars().all()
    return [task_to_dict(row) for row in rows]


def list_task_history(session: Session, task_date: str | None = None) -> list[dict]:
    """已完成任务历史：按完成时间倒序（未知排最后），可按归属日期筛选。历史只读。"""

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
    is_important: bool = False,
) -> dict:
    # 追加到该日期视图末尾（max sort_order + 1）；标记重要时由排序键自动置顶
    max_order = session.execute(
        select(DailyTask.sort_order)
        .where(DailyTask.task_date <= task_date)
        .where(or_(DailyTask.task_date == task_date, DailyTask.done == 0))
        .order_by(DailyTask.sort_order.desc())
    ).scalars().first()
    task = DailyTask(
        task_date=task_date,
        title=title,
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
            if task.done == 1 and done == 0:
                # 历史只读：不允许恢复为未完成（历史视图与旧 API 入口同受限）
                raise DomainError(
                    "已完成任务不可恢复为未完成（历史仅用于查看）",
                    code="history_readonly",
                    status_code=409,
                )
            # 完成 → 记录完成时间
            task.completed_at = _now()
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
    """统一待办重排：ordered_ids 须与该日期视图全部可见任务完全一致（409 兜底）。

    今日任务与逾期任务可自由穿插；仅写 sort_order，不修改任务日期、完成状态等；
    列表仍按（重要 > sort_order）排序，普通上移/下移不会突破重要优先级。
    """

    rows = session.execute(_visible_statement(task_date)).scalars().all()
    by_id = {row.id: row for row in rows}
    if len(ordered_ids) != len(by_id) or any(task_id not in by_id for task_id in ordered_ids):
        raise DomainError(
            f"排序列表与 {task_date} 待办视图的任务不一致",
            code="reorder_mismatch",
            status_code=409,
        )
    for index, task_id in enumerate(ordered_ids):
        by_id[task_id].sort_order = index + 1
    session.commit()
    return list_daily(session, task_date)
