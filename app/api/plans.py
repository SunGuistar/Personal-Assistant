"""长期计划路由（薄层：校验 → service → 出 schema）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..schemas.plan import PlanDetailOut, PlanIn, PlanOut, PlanPatch
from ..services import plans_service
from .deps import get_session

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[PlanOut])
def list_plans(session: Session = Depends(get_session)):
    return plans_service.list_plans(session)


@router.post("", response_model=PlanOut, status_code=201)
def create_plan(payload: PlanIn, session: Session = Depends(get_session)):
    return plans_service.create_plan(session, **payload.model_dump())


@router.get("/{plan_id}", response_model=PlanDetailOut)
def get_plan(plan_id: int, session: Session = Depends(get_session)):
    return plans_service.get_plan(session, plan_id)


@router.patch("/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, payload: PlanPatch, session: Session = Depends(get_session)):
    return plans_service.update_plan(session, plan_id, payload.model_dump(exclude_unset=True))


@router.delete("/{plan_id}", status_code=204)
def delete_plan(plan_id: int, session: Session = Depends(get_session)):
    plans_service.delete_plan(session, plan_id)
