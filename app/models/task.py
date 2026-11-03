"""后台任务表：状态机 pending → running → success | failed（AGENTS §3 四态）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

TASK_STATUS = ("pending", "running", "success", "failed")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)

    __table_args__ = (
        # 重复提交保护：同 kind 只允许一个未完成任务（SQLite 部分索引）
        Index(
            "ux_tasks_active_kind",
            "kind",
            unique=True,
            sqlite_where=status.in_(["pending", "running"]),
        ),
    )
