"""每周回顾模型（阶段一）：周报草稿/正式周报、对话、建议。

状态机（review_service 维护）：
- weekly_reviews.status: draft → confirmed（单向，确认后不可覆盖/撤销/删除）。
  同周唯一正式周报由部分唯一索引保证（week_start, WHERE status='confirmed'）。
- weekly_review_suggestions.status: pending → accepted | modified | rejected。
  已处置建议不被重新生成无提示覆盖（service 层规则）。

第一版不接 Chroma；周报长期保留，不参与微信缓存清理（清理模块只碰微信两库）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

REVIEW_STATUS = ("draft", "confirmed")
SUGGESTION_STATUS = ("pending", "accepted", "modified", "rejected")

# 建议依据允许的数据来源类型（与 review_service.validate_basis 对应）
BASIS_SOURCE_TYPES = ("daily_task", "long_term_plan", "memo", "important_info", "book", "book_note")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class WeeklyReview(Base):
    __tablename__ = "weekly_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_start: Mapped[str] = mapped_column(String(10))  # 自然周周一 YYYY-MM-DD
    week_end: Mapped[str] = mapped_column(String(10))  # 周日 YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(16), default="draft")
    stats_json: Mapped[str] = mapped_column(Text, default="{}")  # 确定性事实统计（生成时快照）
    analysis_md: Mapped[str] = mapped_column(Text, default="")  # 分析正文（建议生成时由 LLM 产出，确认前可编辑）
    user_notes: Mapped[str] = mapped_column(Text, default="")  # 用户补充信息（确认前可编辑）
    report_md: Mapped[str | None] = mapped_column(Text, nullable=True)  # 正式周报（确认时定稿）
    confirmed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)

    __table_args__ = (
        # 同一自然周只允许一份正式周报（SQLite 部分唯一索引，confirmed 唯一）
        Index(
            "ux_weekly_reviews_confirmed_week",
            "week_start",
            unique=True,
            sqlite_where=status.in_(["confirmed"]),
        ),
    )


class WeeklyReviewMessage(Base):
    __tablename__ = "weekly_review_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("weekly_reviews.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class WeeklyReviewSuggestion(Base):
    __tablename__ = "weekly_review_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("weekly_reviews.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)  # 展示顺序
    content: Mapped[str] = mapped_column(Text)
    # 结构化依据 JSON 数组：[{source_type, source_id, reason, fact}]；
    # fact 为后端校验时回填的记录事实摘要；空数组 = 一般性建议（无数据依据）
    basis_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    final_content: Mapped[str | None] = mapped_column(Text, nullable=True)  # 接受/修改后的最终文本
    reject_reason: Mapped[str] = mapped_column(Text, default="")
    resolved_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)
