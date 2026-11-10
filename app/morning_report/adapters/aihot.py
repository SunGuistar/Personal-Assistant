"""AIHOT 精选资讯接入（D01/V0.6.1 §4.1：/api/v1/items mode=selected 为主入口）。

- publishedAt 是晨报窗口判断的原始发布时间；discoveredAt 仅发现时间，不使用。
- 游标分页取全候选，调用方按窗口本地过滤。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from . import NewsCandidate
from .http_common import fetch_text

logger = logging.getLogger(__name__)

API = "https://aihot.news/api/v1/items"
CST = timezone(timedelta(hours=8))
MAX_PAGES = 10  # 防御：单轮最多翻 10 页


def _to_cst(iso: str) -> str | None:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(CST).isoformat()


def fetch_selected(limit_per_page: int = 50, max_pages: int = MAX_PAGES) -> list[NewsCandidate]:
    """拉取精选列表全部可得页（默认上限 10 页，防失控）。"""

    import json

    out: list[NewsCandidate] = []
    cursor: str | None = None
    for _ in range(max_pages):
        params: dict = {"mode": "selected", "window": "24h", "limit": str(limit_per_page)}
        if cursor:
            params["cursor"] = cursor
        body = json.loads(fetch_text(API, params=params))
        for item in body.get("items", []):
            links = item.get("links") or {}
            out.append(NewsCandidate(
                category="ai",
                title=(item.get("title") or "").strip(),
                summary=(item.get("summary") or "").strip(),
                source_name=(item.get("source") or {}).get("name") or (item.get("source") or {}).get("title") or "AIHOT",
                source_url=links.get("original") or links.get("url") or "",
                published_at=_to_cst(item["publishedAt"]) if item.get("publishedAt") else None,
                adapter="aihot",
                raw={"item_id": item.get("id"), "discovered_at": item.get("discoveredAt")},
            ))
        page = body.get("page") or {}
        if not page.get("hasMore") or not page.get("nextCursor"):
            break
        cursor = page["nextCursor"]
    return out
