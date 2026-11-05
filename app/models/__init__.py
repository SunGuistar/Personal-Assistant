"""SQLAlchemy 模型（hub.db，均经 Alembic 迁移创建）。

news 两表为短期资讯缓存（PRD §2.2 最终版：近期热门 TOP 10 + 外部导航）。
收藏/已读字段为历史遗留，平台功能已取消，业务代码不再读写；
模型继续注册以维持 Base.metadata 与库结构一致。
"""

from __future__ import annotations

from .chat import ChatMessage, ChatSession
from .important_info import ImportantInfo
from .news import NewsItem, NewsSource
from .plan import DailyTask, LongTermPlan
from .reading import Book, BookNote
from .sync import SyncCursor
from .task import Task
from .token_usage import TokenUsage

__all__ = [
    "Book",
    "BookNote",
    "ChatMessage",
    "ChatSession",
    "DailyTask",
    "ImportantInfo",
    "LongTermPlan",
    "NewsItem",
    "NewsSource",
    "SyncCursor",
    "Task",
    "TokenUsage",
]
