"""RSS/Atom 适配器：feedparser 解析（GitHub 官方博客、Python/TypeScript
官方博客、AI 厂商博客等一切 RSS/Atom 来源）。

RSS 无点赞/Star 等互动指标，heat_raw 恒为 0；归一化策略由评分层
给出中性默认值（见 services/news_scoring.py），不视为零价值。
时间无时区信息时按 UTC 处理（feedparser 的 *_parsed 字段统一为 UTC）。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import feedparser
import httpx

from .news_common import MAX_ITEMS_PER_SOURCE, NewsAdapterError, RawNewsItem, fetch_bytes

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str, limit: int = 300) -> str:
    """去标签、压空白，截断为短摘要。"""

    plain = _WS_RE.sub(" ", _TAG_RE.sub(" ", text or "")).strip()
    return plain[:limit]


class RssAdapter:
    kind = "rss"

    def __init__(self, endpoint: str, client: httpx.Client | None = None) -> None:
        if not endpoint:
            raise NewsAdapterError("RSS 来源缺少 endpoint")
        self.endpoint = endpoint
        self.client = client

    def fetch(self) -> list[RawNewsItem]:
        content = fetch_bytes(self.endpoint, client=self.client)
        feed = feedparser.parse(content)
        if feed.bozo and not feed.entries:
            raise NewsAdapterError(f"RSS 解析失败: {getattr(feed, 'bozo_exception', 'unknown')}")

        items: list[RawNewsItem] = []
        for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:
            title = (getattr(entry, "title", "") or "").strip()
            link = (getattr(entry, "link", "") or "").strip()
            if not title or not link:
                continue
            parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
            if parsed:
                published = datetime(*parsed[:6], tzinfo=timezone.utc)
            else:  # 无时间条目按抓取时间处理，避免为空
                published = datetime.now(tz=timezone.utc)
                logger.debug("RSS 条目缺时间，按当前时间: %s", link)
            summary = strip_html(getattr(entry, "summary", "") or "")
            items.append(
                RawNewsItem(
                    title=title,
                    url=link,
                    published_at=published,
                    raw_summary=summary,
                    heat_raw=0.0,
                )
            )
        return items
