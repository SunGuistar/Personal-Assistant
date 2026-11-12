"""用户手动维护的每日问答。"""
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ..db import Base
from .memo import _now


class DailyQuestion(Base):
    __tablename__ = "daily_questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(String(500))
    answer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)
