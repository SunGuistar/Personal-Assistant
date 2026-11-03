"""数据库连接与会话管理（hub.db）。

Schema 变更唯一通道是 Alembic（AGENTS §5）；本模块不 create_all。
FastAPI 依赖（get_session）见 app/api/deps.py，本模块保持框架无关。
聊天两库不在这里管理（阶段 3 经 wechat_agent 访问）。
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(db_url: str):
    return create_engine(db_url, connect_args={"check_same_thread": False})


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
