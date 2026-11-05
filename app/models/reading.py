"""阅读管理模型：书籍与笔记附件（PRD §2.4）。

删除规则：存在关联笔记的书籍禁止删除（Service 层校验，409 book_has_notes），
故 books 删除时不会留下孤儿笔记；book_notes 上的 ON DELETE CASCADE
仅作外键完整性兜底。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

BOOK_STATUS = ("todo", "reading", "done")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(128), default="")
    note: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[str] = mapped_column(String(16), default="todo")
    is_important: Mapped[int] = mapped_column(Integer, default=0)  # 重要置顶（筛选内 重要 > 默认排序）
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)


class BookNote(Base):
    __tablename__ = "book_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(500))
    size: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[str] = mapped_column(String(32), default=_now)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
