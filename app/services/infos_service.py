"""重要信息业务逻辑（右侧常驻栏）：多条长期保存记录的 CRUD 与手动排序。

排序规则与计划一致：sort_order 全表统一（列表按 sort_order > id 展示），
上移/下移提交完整顺序（PUT /infos/reorder）。
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..exceptions import DomainError, NotFoundError
from ..models import ImportantInfo


def info_to_dict(info: ImportantInfo) -> dict:
    return {
        "id": info.id,
        "title": info.title,
        "content": info.content,
        "sort_order": info.sort_order,
        "created_at": info.created_at,
        "updated_at": info.updated_at,
    }


def list_infos(session: Session) -> list[dict]:
    rows = session.execute(select(ImportantInfo).order_by(ImportantInfo.sort_order, ImportantInfo.id)).scalars().all()
    return [info_to_dict(row) for row in rows]


def create_info(session: Session, *, title: str, content: str = "") -> dict:
    max_order = session.execute(select(ImportantInfo.sort_order).order_by(ImportantInfo.sort_order.desc())).scalars().first()
    info = ImportantInfo(title=title, content=content, sort_order=(max_order or 0) + 1)
    session.add(info)
    session.commit()
    session.refresh(info)
    return info_to_dict(info)


def update_info(session: Session, info_id: int, fields: dict) -> dict:
    info = session.get(ImportantInfo, info_id)
    if info is None:
        raise NotFoundError(f"重要信息不存在: {info_id}")
    if fields.get("title") is not None:
        info.title = fields["title"]
    if fields.get("content") is not None:
        info.content = fields["content"]
    session.commit()
    session.refresh(info)
    return info_to_dict(info)


def delete_info(session: Session, info_id: int) -> None:
    info = session.get(ImportantInfo, info_id)
    if info is None:
        raise NotFoundError(f"重要信息不存在: {info_id}")
    session.execute(delete(ImportantInfo).where(ImportantInfo.id == info_id))
    session.commit()


def reorder_infos(session: Session, ordered_ids: list[int]) -> list[dict]:
    """按 ordered_ids 整体重排；任何 id 不属于现有记录则整体拒绝（409）。"""

    rows = session.execute(select(ImportantInfo)).scalars().all()
    by_id = {row.id: row for row in rows}
    if len(ordered_ids) != len(by_id) or any(info_id not in by_id for info_id in ordered_ids):
        raise DomainError(
            "排序列表与现有重要信息不一致",
            code="reorder_mismatch",
            status_code=409,
        )
    for index, info_id in enumerate(ordered_ids):
        by_id[info_id].sort_order = index + 1
    session.commit()
    return list_infos(session)
