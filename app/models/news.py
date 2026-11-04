"""资讯中心模型（PRD §2.2 / ARCH §3.2）：来源配置与资讯条目。

时间约定：created_at/updated_at/fetched_at 为本地 ISO8601 秒级文本；
published_at 统一为 UTC ISO8601 带 +00:00 偏移（RSS 无时区按 UTC 处理），
供时效评分与 7 天过期判定（以 published_at 为准，已收藏豁免）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

SOURCE_KINDS = ("rss", "hn")  # github 官方博客等 RSS/Atom 源一律走 rss 抓取（ARCH kind 的兼容收窄）

TOPICS = ("ai", "agent", "engineering", "python", "typescript", "ai_coding", "opensource", "other")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(16))  # rss / hn
    endpoint: Mapped[str] = mapped_column(String(512))
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("url", name="uq_news_items_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024))  # 规范化后的 URL，全局唯一
    source: Mapped[str] = mapped_column(String(64))  # 冗余来源名，列表免 join
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("news_sources.id", ondelete="SET NULL"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(32), default="other")
    published_at: Mapped[str] = mapped_column(String(40))  # UTC ISO8601（+00:00）
    raw_summary: Mapped[str] = mapped_column(Text, default="")
    heat_raw: Mapped[float] = mapped_column(Float, default=0.0)  # 原始热度（HN points；RSS 为 0）
    norm_heat: Mapped[float] = mapped_column(Float, default=0.0)  # 按来源归一化 [0,1]
    score: Mapped[float] = mapped_column(Float, default=0.0)  # 综合分 = norm_heat × weight × age_decay
    is_favorite: Mapped[int] = mapped_column(Integer, default=0)
    is_read: Mapped[int] = mapped_column(Integer, default=0)
    title_hash: Mapped[str] = mapped_column(String(64), default="")  # 标题哈希去重（sha1）
    fetched_at: Mapped[str] = mapped_column(String(32), default=_now)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)
