"""随手备忘业务逻辑（SQLite 多条记录）：CRUD、排序，及与每日任务的双向转换。

随手备忘 = 待处理想法/未定时任务（缓冲池）；最终去向只有删除或转为每日任务。
与重要信息（important_infos）概念独立，不合并。

双向转换是"移动"不是"复制"：单事务内先建目标、后删原记录，任一步失败整体回滚；
转换后源记录不存在，重复请求自然 404（天然防重复点击）。
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..exceptions import DomainError, NotFoundError
from ..models import DailyTask, Memo
from ..models.plan import TASK_TYPES
from . import tasks_service


def memo_to_dict(memo: Memo) -> dict:
    return {
        "id": memo.id,
        "title": memo.title,
        "content": memo.content,
        "sort_order": memo.sort_order,
        "created_at": memo.created_at,
        "updated_at": memo.updated_at,
    }


def list_memos(session: Session) -> list[dict]:
    rows = session.execute(select(Memo).order_by(Memo.sort_order, Memo.id)).scalars().all()
    return [memo_to_dict(row) for row in rows]


def create_memo(session: Session, *, title: str, content: str = "") -> dict:
    max_order = session.execute(select(Memo.sort_order).order_by(Memo.sort_order.desc())).scalars().first()
    memo = Memo(title=title, content=content, sort_order=(max_order or 0) + 1)
    session.add(memo)
    session.commit()
    session.refresh(memo)
    return memo_to_dict(memo)


def update_memo(session: Session, memo_id: int, fields: dict) -> dict:
    memo = session.get(Memo, memo_id)
    if memo is None:
        raise NotFoundError(f"随手备忘不存在: {memo_id}")
    if fields.get("title") is not None:
        memo.title = fields["title"]
    if fields.get("content") is not None:
        memo.content = fields["content"]
    session.commit()
    session.refresh(memo)
    return memo_to_dict(memo)


def delete_memo(session: Session, memo_id: int) -> None:
    memo = session.get(Memo, memo_id)
    if memo is None:
        raise NotFoundError(f"随手备忘不存在: {memo_id}")
    session.execute(delete(Memo).where(Memo.id == memo_id))
    session.commit()


def reorder_memos(session: Session, ordered_ids: list[int]) -> list[dict]:
    """整体重排；任何 id 不属于现有记录则整体拒绝（409）。"""

    rows = session.execute(select(Memo)).scalars().all()
    by_id = {row.id: row for row in rows}
    if len(ordered_ids) != len(by_id) or any(memo_id not in by_id for memo_id in ordered_ids):
        raise DomainError(
            "排序列表与现有随手备忘不一致",
            code="reorder_mismatch",
            status_code=409,
        )
    for index, memo_id in enumerate(ordered_ids):
        by_id[memo_id].sort_order = index + 1
    session.commit()
    return list_memos(session)


def get_memo(session: Session, memo_id: int) -> Memo:
    memo = session.get(Memo, memo_id)
    if memo is None:
        raise NotFoundError(f"随手备忘不存在: {memo_id}")
    return memo


# ---------- 双向转换（移动，单事务原子） ----------

def memo_to_task(
    session: Session,
    memo_id: int,
    *,
    task_date: str,
    task_type: str = "daily",
    is_important: bool = False,
) -> dict:
    """随手备忘 → 每日任务：标题/内容完整迁移，原备忘删除；失败整体回滚。"""

    if task_type not in TASK_TYPES:
        raise DomainError(
            f"非法任务类型: {task_type}", code="invalid_task_type", status_code=400
        )
    memo = get_memo(session, memo_id)  # 不存在 → 404（重复转换/重复点击安全）

    max_order = session.execute(
        select(DailyTask.sort_order)
        .where(DailyTask.task_date <= task_date)
        .where((DailyTask.task_date == task_date) | (DailyTask.done == 0))
        .order_by(DailyTask.sort_order.desc())
    ).scalars().first()
    task = DailyTask(
        task_date=task_date,
        title=memo.title,
        content=memo.content or None,  # 内容不静默丢弃
        task_type=task_type,
        is_important=1 if is_important else 0,
        sort_order=(max_order or 0) + 1,
    )
    session.add(task)
    session.flush()          # 先确保目标记录创建成功
    session.delete(memo)     # 再移除原记录
    session.commit()
    session.refresh(task)
    return tasks_service.task_to_dict(task)


def task_to_memo(session: Session, task_id: int) -> dict:
    """每日任务 → 随手备忘：仅未完成可转换；标题/内容迁移，原任务删除。"""

    task = tasks_service.get_task(session, task_id)
    if task.done:
        raise DomainError(
            "已完成的历史任务不能转为随手备忘（避免破坏完成记录）",
            code="task_done_not_convertible",
            status_code=409,
        )
    max_order = session.execute(select(Memo.sort_order).order_by(Memo.sort_order.desc())).scalars().first()
    memo = Memo(
        title=task.title,
        content=task.content or "",
        sort_order=(max_order or 0) + 1,
    )
    session.add(memo)
    session.flush()
    session.delete(task)
    session.commit()
    session.refresh(memo)
    return memo_to_dict(memo)
