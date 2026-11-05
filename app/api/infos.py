"""右侧常驻栏 API：重要信息（SQLite，多条）+ 随手备忘（本地 Markdown 文件）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..schemas.info import InfoIn, InfoOut, InfoPatch, InfoReorderIn, MemoIn, MemoOut
from ..services import infos_service, memo_service
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


memo_router = APIRouter(prefix="/memo", tags=["memo"])


@memo_router.get("", response_model=MemoOut)
def get_memo():
    """读取随手备忘；文件不存在按空内容处理。"""

    return {"content": memo_service.read_memo()}


@memo_router.put("", response_model=MemoOut)
def put_memo(payload: MemoIn):
    """保存随手备忘（原子写入；expected 提供时防乱序覆盖，冲突返回 409）。"""

    memo_service.write_memo(payload.content, expected=payload.expected)
    return {"content": payload.content}
