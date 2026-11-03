"""FastAPI 依赖：每个 app 实例的状态存取（settings / session / task_runner）。"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from ..config import Settings
from ..tasks import TaskRunner


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


def get_task_runner(request: Request) -> TaskRunner:
    return request.app.state.task_runner
