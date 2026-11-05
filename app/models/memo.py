"""随手备忘模型（右侧常驻栏下部）：多条结构化记录，SQLite 持久化。

定位：暂时搁置的想法/未定时任务/每日计划的"缓冲池"；最终去向只有两种——
删除或转为每日任务。与重要信息（important_infos）同规范但概念独立，不合并。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Memo(Base):
    __tablename__ = "memos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)
