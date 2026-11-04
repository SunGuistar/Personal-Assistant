"""微信同步游标（hub.db）：游标只在消息持久化提交后推进。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class SyncCursor(Base):
    __tablename__ = "sync_cursors"

    scope: Mapped[str] = mapped_column(String(128), primary_key=True)  # chat_id
    last_timestamp: Mapped[int] = mapped_column(Integer, default=0)
    last_msg_id: Mapped[str] = mapped_column(String(128), default="")
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)
