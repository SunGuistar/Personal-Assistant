"""右侧常驻栏 API：重要信息（infos）+ 随手备忘（memos），均为 SQLite 多条记录。

随手备忘提供与每日任务的双向转换（移动语义，单事务原子）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..schemas.info import InfoIn, InfoOut, InfoPatch, InfoReorderIn
from ..schemas.info import MemoIn, MemoOut, MemoPatch, MemoReorderIn
from ..schemas.plan import DailyTaskOut, MemoToTaskIn
from ..services import infos_service, memos_service
from .deps import get_session

infos_router = APIRouter(prefix="/infos", tags=["infos"])


@infos_router.get("", response_model=list[InfoOut])
def list_infos(session: Session = Depends(get_session)):
    return infos_service.list_infos(session)


@infos_router.post("", response_model=InfoOut, status_code=201)
def create_info(payload: InfoIn, session: Session = Depends(get_session)):
    return infos_service.create_info(session, **payload.model_dump())


@infos_router.patch("/{info_id}", response_model=InfoOut)
def update_info(info_id: int, payload: InfoPatch, session: Session = Depends(get_session)):
    return infos_service.update_info(session, info_id, payload.model_dump(exclude_unset=True))


@infos_router.delete("/{info_id}", status_code=204)
def delete_info(info_id: int, session: Session = Depends(get_session)):
    infos_service.delete_info(session, info_id)


@infos_router.put("/reorder", response_model=list[InfoOut])
def reorder_infos(payload: InfoReorderIn, session: Session = Depends(get_session)):
    return infos_service.reorder_infos(session, payload.ordered_ids)


memos_router = APIRouter(prefix="/memos", tags=["memos"])


@memos_router.get("", response_model=list[MemoOut])
def list_memos(session: Session = Depends(get_session)):
    return memos_service.list_memos(session)


@memos_router.post("", response_model=MemoOut, status_code=201)
def create_memo(payload: MemoIn, session: Session = Depends(get_session)):
    return memos_service.create_memo(session, **payload.model_dump())


@memos_router.patch("/{memo_id}", response_model=MemoOut)
def update_memo(memo_id: int, payload: MemoPatch, session: Session = Depends(get_session)):
    return memos_service.update_memo(session, memo_id, payload.model_dump(exclude_unset=True))


@memos_router.delete("/{memo_id}", status_code=204)
def delete_memo(memo_id: int, session: Session = Depends(get_session)):
    memos_service.delete_memo(session, memo_id)


@memos_router.put("/reorder", response_model=list[MemoOut])
def reorder_memos(payload: MemoReorderIn, session: Session = Depends(get_session)):
    return memos_service.reorder_memos(session, payload.ordered_ids)


@memos_router.post("/{memo_id}/to_task", response_model=DailyTaskOut)
def memo_to_task(memo_id: int, payload: MemoToTaskIn, session: Session = Depends(get_session)):
    """随手备忘 → 每日任务（移动）：原备忘删除，标题/内容完整迁移。"""

    return memos_service.memo_to_task(
        session,
        memo_id,
        task_date=payload.target_date,
        task_type=payload.task_type,
        is_important=payload.is_important,
    )
