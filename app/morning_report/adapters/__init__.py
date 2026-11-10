"""外部资讯源适配层（AIHOT / 中新网归档 / 热摸爽）。

统一产出 NewsCandidate；各源只做获取与字段映射，业务过滤在 services/news_pipeline。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NewsCandidate:
    category: str  # domestic/international/ai
    title: str
    summary: str
    source_name: str
    source_url: str
    published_at: str | None  # ISO8601 CST；None=无可靠时间（仅线索）
    adapter: str  # aihot/chinanews/remoshuang
    raw: dict = field(default_factory=dict)
