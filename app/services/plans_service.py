"""长期计划业务逻辑（PRD §2.3 + 重要置顶/历史视图优化）。纯函数式 service：接收 Session，不依赖 FastAPI。

排序规则（每日计划与长期计划一致）：重要状态 > 手动排序顺序（sort_order）。
完成机制：仅经"标记完成"（complete_plan）进入已完成；completed_at 记录完成时间，
存量完成时间未知保持 NULL，历史视图显示"完成时间未知"。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..exceptions import DomainError, NotFoundError
from ..models import DailyTask, LongTermPlan
from ..models.plan import PLAN_STATUS


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def plan_to_dict(plan: LongTermPlan) -> dict:
    return {
        "id": plan.id,
        "title": plan.title,
        "description": plan.description,
        "status": plan.status,
        "target_date": plan.target_date,
        "is_important": bool(plan.is_important),
        "sort_order": plan.sort_order,
        "completed_at": plan.completed_at,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def _active_plans_query():
    """活动计划（未完成）：重要 > sort_order > id。"""

    return (
        select(LongTermPlan)
        .where(LongTermPlan.status != "completed")
        .order_by(LongTermPlan.is_important.desc(), LongTermPlan.sort_order, LongTermPlan.id)
    )


def list_plans(session: Session) -> list[dict]:
    """当前长期计划（不含已完成；已完成的经历史视图查询）。"""

    plans = session.execute(_active_plans_query()).scalars().all()
    return [plan_to_dict(plan) for plan in plans]


def list_plan_history(session: Session) -> list[dict]:
    """历史计划：按完成时间倒序；完成时间未知（NULL）排最后，不伪造时间。"""

    completed_flag = LongTermPlan.completed_at.is_(None)
    plans = session.execute(
        select(LongTermPlan)
        .where(LongTermPlan.status == "completed")
        .order_by(completed_flag, LongTermPlan.completed_at.desc(), LongTermPlan.id.desc())
    ).scalars().all()
    return [plan_to_dict(plan) for plan in plans]


def get_plan(session: Session, plan_id: int) -> dict:
    plan = session.get(LongTermPlan, plan_id)
    if plan is None:
        raise NotFoundError(f"长期计划不存在: {plan_id}")
    data = plan_to_dict(plan)
    tasks = session.execute(
        select(DailyTask).where(DailyTask.plan_id == plan_id).order_by(DailyTask.task_date, DailyTask.sort_order)
    ).scalars().all()
    data["task_ids"] = [task.id for task in tasks]
    return data


def create_plan(
    session: Session,
    *,
    title: str,
    description: str = "",
    status: str = "in_progress",
    target_date: str | None = None,
    is_important: bool = False,
) -> dict:
    if status not in PLAN_STATUS:
        raise NotFoundError(f"非法计划状态: {status}")  # 422 由路由参数校验兜底
    max_order = session.execute(select(LongTermPlan.sort_order).order_by(LongTermPlan.sort_order.desc())).scalars().first()
    plan = LongTermPlan(
        title=title,
        description=description,
        status=status,
        target_date=target_date,
        is_important=1 if is_important else 0,
        sort_order=(max_order or 0) + 1,
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan_to_dict(plan)


def update_plan(session: Session, plan_id: int, fields: dict) -> dict:
    plan = session.get(LongTermPlan, plan_id)
    if plan is None:
        raise NotFoundError(f"长期计划不存在: {plan_id}")
    for key in ("title", "description", "status", "target_date"):
        if key in fields and fields[key] is not None:
            setattr(plan, key, fields[key])
    # 经 PATCH 直接置为已完成时同样补记完成时间（UI 主通道为"标记完成"按钮）
    if plan.status == "completed" and plan.completed_at is None:
        plan.completed_at = _now()
    if fields.get("is_important") is not None:
        plan.is_important = 1 if fields["is_important"] else 0
    session.commit()
    session.refresh(plan)
    return plan_to_dict(plan)


def complete_plan(session: Session, plan_id: int) -> dict:
    """标记完成：记录完成时间并移入历史（status=completed 即离开当前列表）。"""

    plan = session.get(LongTermPlan, plan_id)
    if plan is None:
        raise NotFoundError(f"长期计划不存在: {plan_id}")
    plan.status = "completed"
    plan.completed_at = _now()
    session.commit()
    session.refresh(plan)
    return plan_to_dict(plan)


def reorder_plans(session: Session, ordered_ids: list[int]) -> list[dict]:
    """按 ordered_ids 重排活动计划；任何 id 不属于活动计划则整体拒绝（409）。

    排序键为（重要 > sort_order）：前端提交完整展示顺序（重要在前），
    后端按位置写入 sort_order，取消重要后自动回落到普通区域。
    """

    rows = session.execute(
        select(LongTermPlan).where(LongTermPlan.status != "completed")
    ).scalars().all()
    by_id = {row.id: row for row in rows}
    if len(ordered_ids) != len(by_id) or any(plan_id not in by_id for plan_id in ordered_ids):
        raise DomainError(
            "排序列表与当前长期计划不一致",
            code="reorder_mismatch",
            status_code=409,
        )
    for index, plan_id in enumerate(ordered_ids):
        by_id[plan_id].sort_order = index + 1
    session.commit()
    return list_plans(session)


def delete_plan(session: Session, plan_id: int) -> None:
    """删除长期计划（活动与历史通用）：关联每日任务的 plan_id 置空保留（不删任务、不级联）。"""

    plan = session.get(LongTermPlan, plan_id)
    if plan is None:
        raise NotFoundError(f"长期计划不存在: {plan_id}")
    session.execute(update(DailyTask).where(DailyTask.plan_id == plan_id).values(plan_id=None))
    session.execute(delete(LongTermPlan).where(LongTermPlan.id == plan_id))
    session.commit()
