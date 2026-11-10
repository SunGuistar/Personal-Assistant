"""清理审核模型（阶段 5，D4）：审核周期、候选分组、删除计划明细、审计。

聊天正文不落库：候选与明细只记 ID、数量、时间戳与状态。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

REVIEW_STATUS = ("pending", "dismissed", "done", "skipped")
CANDIDATE_STATES = ("pending", "validated", "deleted", "failed", "failed_protected")
ITEM_KINDS = ("normalized", "snapshot", "chunk")
ITEM_STATES = ("pending", "validated", "done", "failed")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class CleanupReview(Base):
    __tablename__ = "cleanup_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_id: Mapped[str] = mapped_column(String(16), unique=True)  # 所在周日 YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(16), default="pending")
    summary: Mapped[str] = mapped_column(Text, default="")  # 审核说明（生成候选时写入）
    confirmed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)


class CleanupCandidate(Base):
    __tablename__ = "cleanup_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(Integer)
    chat_id: Mapped[str] = mapped_column(String(64))
    chat_name: Mapped[str] = mapped_column(String(128), default="")
    msg_date: Mapped[str] = mapped_column(String(10))
    snapshot_count: Mapped[int] = mapped_column(Integer, default=0)
    normalized_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_delete_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_keep_count: Mapped[int] = mapped_column(Integer, default=0)
    keep_reasons: Mapped[str] = mapped_column(Text, default="[]")  # JSON [{chunk_id, reason}]
    size_estimate: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)


class CleanupDeleteItem(Base):
    __tablename__ = "cleanup_delete_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(Integer)
    candidate_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # normalized / snapshot / chunk
    ref_id: Mapped[str] = mapped_column(String(128), default="")
    state: Mapped[str] = mapped_column(String(16), default="pending")
    detail: Mapped[str] = mapped_column(Text, default="{}")  # JSON 校验快照（时间戳区间等）
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)


class CleanupAudit(Base):
    __tablename__ = "cleanup_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(Integer)
    item_type: Mapped[str] = mapped_column(String(32))
    count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
