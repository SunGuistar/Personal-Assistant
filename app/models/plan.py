"""计划管理模型：长期计划与每日任务（PRD §2.3）。

2026-11 综合优化轮：两模块彻底独立——daily_tasks 不再含 plan_id；
排序统一为 重要(is_important) > sort_order；长期计划新增 goal（具体目标）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

PLAN_STATUS = ("in_progress", "completed", "on_hold")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class LongTermPlan(Base):
    __tablename__ = "long_term_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)  # 具体目标（可选，多行文本）
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    target_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_important: Mapped[int] = mapped_column(Integer, default=0)  # 重要置顶（排序：重要 > sort_order）
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 标记完成时间；未知为 NULL
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)


class DailyTask(Base):
    __tablename__ = "daily_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_date: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    done: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_important: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 标记完成时间；未知为 NULL
    moved_from_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)
