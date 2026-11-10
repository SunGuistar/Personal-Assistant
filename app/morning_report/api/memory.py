"""Memory CRUD（V0.6 §4.5：可查看、编辑、禁用、删除）。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...exceptions import NotFoundError
from ..models import Memory
from ..schemas import MemoryIn, MemoryOut, MemoryPatch
from .deps import get_mr_session

router = APIRouter(prefix="/memory")


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


@router.get("", response_model=list[MemoryOut])
def list_memory(mr: Session = Depends(get_mr_session)) -> list[MemoryOut]:
    rows = mr.execute(select(Memory).order_by(Memory.id.desc())).scalars().all()
    return [MemoryOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(body: MemoryIn, mr: Session = Depends(get_mr_session)) -> MemoryOut:
    row = Memory(kind=body.kind, content=body.content, source="manual", confirmed=True)
    mr.add(row)
    mr.commit()
    return MemoryOut.model_validate(row, from_attributes=True)


@router.patch("/{memory_id}", response_model=MemoryOut)
def patch_memory(memory_id: int, body: MemoryPatch, mr: Session = Depends(get_mr_session)) -> MemoryOut:
    row = mr.get(Memory, memory_id)
    if row is None:
        raise NotFoundError("Memory 不存在")
    if body.content is not None:
        row.content = body.content
    if body.enabled is not None:
        row.enabled = body.enabled
    row.updated_at = _now()
    mr.commit()
    return MemoryOut.model_validate(row, from_attributes=True)


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: int, mr: Session = Depends(get_mr_session)) -> None:
    row = mr.get(Memory, memory_id)
    if row is None:
        raise NotFoundError("Memory 不存在")
    mr.delete(row)
    mr.commit()
