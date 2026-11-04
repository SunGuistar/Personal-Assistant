"""SQLAlchemy 模型（hub.db，均经 Alembic 迁移创建）。

news 两表为历史遗留（2026-11 产品调整：资讯改为外部导航，PRD §2.2）：
表与数据按保守策略保留在库中，模型定义继续注册以保持 Base.metadata
与库结构一致（防止未来 autogenerate 对现存表生成 DROP），但业务代码
不再读写它们。
"""

from __future__ import annotations

from .chat import ChatMessage, ChatSession
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
    "LongTermPlan",
    "NewsItem",
    "NewsSource",
    "SyncCursor",
    "Task",
    "TokenUsage",
]
