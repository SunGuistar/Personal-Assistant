"""长期计划业务逻辑（PRD §2.3）。纯函数式 service：接收 Session，不依赖 FastAPI。"""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..exceptions import NotFoundError
from ..models import DailyTask, LongTermPlan
from ..models.plan import PLAN_STATUS


def plan_to_dict(plan: LongTermPlan) -> dict:
    return {
        "id": plan.id,
        "title": plan.title,
        "description": plan.description,
        "status": plan.status,
        "target_date": plan.target_date,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def list_plans(session: Session) -> list[dict]:
    plans = session.execute(select(LongTermPlan).order_by(LongTermPlan.id)).scalars().all()
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
) -> dict:
    if status not in PLAN_STATUS:
        raise NotFoundError(f"非法计划状态: {status}")  # 422 由路由参数校验兜底
    plan = LongTermPlan(title=title, description=description, status=status, target_date=target_date)
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
    session.commit()
    session.refresh(plan)
    return plan_to_dict(plan)


def delete_plan(session: Session, plan_id: int) -> None:
    """删除长期计划：关联每日任务的 plan_id 置空保留（不删任务）。"""

    plan = session.get(LongTermPlan, plan_id)
    if plan is None:
        raise NotFoundError(f"长期计划不存在: {plan_id}")
    session.execute(update(DailyTask).where(DailyTask.plan_id == plan_id).values(plan_id=None))
    session.execute(delete(LongTermPlan).where(LongTermPlan.id == plan_id))
    session.commit()
