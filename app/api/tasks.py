"""每日任务路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..schemas.plan import DailyTaskIn, DailyTaskOut, DailyTaskPatch, MoveTaskIn, ReorderIn
from ..services import tasks_service
from .deps import get_session

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/daily", response_model=list[DailyTaskOut])
def list_daily(date: str, session: Session = Depends(get_session)):
    return tasks_service.list_daily(session, date)


@router.get("/history", response_model=list[DailyTaskOut])
def list_task_history(date: str | None = None, session: Session = Depends(get_session)):
    """已完成任务历史（与 daily_tasks 同表），可按归属日期筛选；默认按完成时间倒序。"""

    return tasks_service.list_task_history(session, date)


@router.post("", response_model=DailyTaskOut, status_code=201)
def create_task(payload: DailyTaskIn, session: Session = Depends(get_session)):
    return tasks_service.create_task(session, **payload.model_dump())


@router.get("/{task_id}", response_model=DailyTaskOut)
def get_task(task_id: int, session: Session = Depends(get_session)):
    return tasks_service.task_to_dict(tasks_service.get_task(session, task_id))


@router.patch("/{task_id}", response_model=DailyTaskOut)
def update_task(task_id: int, payload: DailyTaskPatch, session: Session = Depends(get_session)):
    return tasks_service.update_task(session, task_id, payload.model_dump(exclude_unset=True))


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, session: Session = Depends(get_session)):
    tasks_service.delete_task(session, task_id)


@router.post("/{task_id}/move", response_model=DailyTaskOut)
def move_task(task_id: int, payload: MoveTaskIn, session: Session = Depends(get_session)):
    return tasks_service.move_task(session, task_id, payload.target_date)


@router.put("/reorder", response_model=list[DailyTaskOut])
def reorder_tasks(payload: ReorderIn, session: Session = Depends(get_session)):
    return tasks_service.reorder_tasks(session, payload.date, payload.ordered_ids, payload.scope)
