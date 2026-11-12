"""晨报模块 FastAPI 依赖。"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from ..config import MRSettings


def get_mr_settings(request: Request) -> MRSettings:
    return request.app.state.mr_settings


def get_mr_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.mr_session_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


def get_hub_session(request: Request) -> Iterator[Session]:
    """hub.db 只读访问会话（晨报模块只允许 SELECT，见 services/hub_readonly）。"""

    factory = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()
