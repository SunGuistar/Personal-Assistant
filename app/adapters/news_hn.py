"""Hacker News 适配器：官方 Algolia Search API（免费、无 Key）。

front_page 标签返回当前首页条目，hits 自带 points（热度）与
created_at_i（unix 秒，UTC）。无 url 的 Ask HN 等条目回退到
官方讨论页，保证 url 非空可去重。
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from .news_common import NewsAdapterError, RawNewsItem, fetch_bytes

DEFAULT_ENDPOINT = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"
ITEM_PAGE = "https://news.ycombinator.com/item?id="


class HackerNewsAdapter:
    kind = "hn"

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, client: httpx.Client | None = None) -> None:
        self.endpoint = endpoint or DEFAULT_ENDPOINT
        self.client = client

    def fetch(self) -> list[RawNewsItem]:
        try:
            import json

            payload = json.loads(fetch_bytes(self.endpoint, client=self.client))
        except (ValueError, NewsAdapterError) as exc:
            if isinstance(exc, NewsAdapterError):
                raise
            raise NewsAdapterError(f"HN 响应不是合法 JSON: {exc}") from exc

        hits = payload.get("hits")
        if not isinstance(hits, list):
            raise NewsAdapterError("HN 响应缺少 hits 列表")

        items: list[RawNewsItem] = []
        for hit in hits:
            title = (hit.get("title") or "").strip()
            if not title:
                continue
            object_id = str(hit.get("objectID") or "")
            url = (hit.get("url") or "").strip() or f"{ITEM_PAGE}{quote(object_id)}"
            created = hit.get("created_at_i")
            try:
                published = datetime.fromtimestamp(int(created), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                published = datetime.now(tz=timezone.utc)
            points = float(hit.get("points") or 0)
            items.append(
                RawNewsItem(
                    title=title,
                    url=url,
                    published_at=published,
                    raw_summary=f"HN {points:.0f} points",
                    heat_raw=points,
                )
            )
        return items
