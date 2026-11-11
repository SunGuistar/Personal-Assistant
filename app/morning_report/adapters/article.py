"""入围新闻详情解析：仅提取页面明确给出的时间与正文摘录，不推测日期。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse

from .http_common import fetch_text

CST = timezone(timedelta(hours=8))


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.metadata = {}
        self.text = []
        self.paragraphs = []
        self.skip = 0
        self.paragraph = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
            if key:
                self.metadata[key.lower()] = attrs.get("content", "")
        if tag == "time" and attrs.get("datetime"):
            self.metadata.setdefault("article:published_time", attrs["datetime"])
        if tag == "p" and not self.skip:
            self.paragraph = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag == "p" and self.paragraph is not None:
            self.paragraphs.append("".join(self.paragraph).strip())
            self.paragraph = None

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)
            if self.paragraph is not None:
                self.paragraph.append(data)


def parse_article(html: str) -> dict:
    parser = ArticleParser()
    parser.feed(html)
    stamp = None
    for key in ("article:published_time", "datepublished", "publishdate", "pubdate", "publish_date"):
        value = parser.metadata.get(key)
        if value and re.search(r"[T ]\d{1,2}:\d{2}", value):
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=CST)
                break
            except ValueError:
                continue
    if stamp is None:
        # 页面显式展示的完整日期与时分；不使用 URL 日期或聚合日期补时刻。
        match = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", " ".join(parser.text))
        if match:
            try:
                stamp = datetime(*(int(v or 0) for v in match.groups()), tzinfo=CST)
            except ValueError:
                pass
    paragraphs = [p for p in parser.paragraphs if len(p) >= 30]
    summary = " ".join(paragraphs)[:1800] or parser.metadata.get("description", "")[:1800]
    return {"published_at": stamp.astimezone(CST).isoformat() if stamp else None,
            "summary": summary}


def fetch_article(url: str) -> dict:
    # 仅访问已支持新闻站的公开详情，避免跟随聚合数据中的任意地址。
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("https", "http") or not any(
        host == root or host.endswith("." + root) for root in ("sina.com.cn", "chinanews.com.cn", "chinanews.com")
    ):
        return {"published_at": None, "summary": ""}
    return parse_article(fetch_text(url, timeout=10))
