"""长期计划路由（薄层：校验 → service → 出 schema）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..schemas.plan import PlanIn, PlanOut, PlanPatch, PlanReorderIn
from ..services import plans_service
from .deps import get_session

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[PlanOut])
def list_plans(session: Session = Depends(get_session)):
    return plans_service.list_plans(session)


@router.get("/history", response_model=list[PlanOut])
def list_plan_history(session: Session = Depends(get_session)):
    """历史计划：已标记完成的计划（含存量 completed），按完成时间倒序。"""

    return plans_service.list_plan_history(session)


@router.put("/reorder", response_model=list[PlanOut])
def reorder_plans(payload: PlanReorderIn, session: Session = Depends(get_session)):
    return plans_service.reorder_plans(session, payload.ordered_ids)


@router.post("", response_model=PlanOut, status_code=201)
def create_plan(payload: PlanIn, session: Session = Depends(get_session)):
    return plans_service.create_plan(session, **payload.model_dump())


@router.get("/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: int, session: Session = Depends(get_session)):
    return plans_service.get_plan(session, plan_id)


@router.patch("/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, payload: PlanPatch, session: Session = Depends(get_session)):
    return plans_service.update_plan(session, plan_id, payload.model_dump(exclude_unset=True))


@router.post("/{plan_id}/complete", response_model=PlanOut)
def complete_plan(plan_id: int, session: Session = Depends(get_session)):
    """标记完成：记录完成时间，移入历史计划（确认交互由前端负责）。"""

    return plans_service.complete_plan(session, plan_id)


@router.delete("/{plan_id}", status_code=204)
def delete_plan(plan_id: int, session: Session = Depends(get_session)):
    plans_service.delete_plan(session, plan_id)
