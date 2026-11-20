"""经验记录的浏览和保存，不执行删除或模型调用。"""
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from ..exceptions import DomainError, NotFoundError
from ..models.experience import Experience


def _check_schema(session: Session) -> None:
    if not inspect(session.connection()).has_table(Experience.__tablename__):
        raise DomainError("经验库数据库尚未迁移，请先完成数据库迁移后重试。",
                          code="experiences_schema_missing", status_code=503)


def list_experiences(session: Session) -> list[Experience]:
    _check_schema(session)
    return list(session.scalars(select(Experience).order_by(Experience.updated_at.desc(), Experience.id.desc())))


def save_experience(session: Session, payload: dict, experience_id: int | None = None) -> Experience:
    _check_schema(session)
    item = session.get(Experience, experience_id) if experience_id is not None else Experience()
    if item is None:
        raise NotFoundError("经验记录不存在")
    for name, value in payload.items():
        setattr(item, name, value.strip())
    session.add(item)
    session.commit()
    session.refresh(item)
    return item
