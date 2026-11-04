"""资讯适配器解析单元测试（fixture 驱动，零外网）。"""

from __future__ import annotations

from datetime import timezone

from app.adapters.news_hn import HackerNewsAdapter
from app.adapters.news_rss import RssAdapter, strip_html

ATOM_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Blog</title>
  <entry>
    <title>Release 2.0 of Demo Framework</title>
    <link href="https://example.com/posts/2?utm_source=feed"/>
    <updated>2026-11-09T08:00:00Z</updated>
    <summary type="html">&lt;p&gt;Big &lt;b&gt;release&lt;/b&gt; notes&lt;/p&gt;</summary>
  </entry>
  <entry>
    <title>No Link Entry</title>
    <updated>2026-11-08T08:00:00Z</updated>
  </entry>
</feed>
"""

RSS_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Py Feed</title>
<item>
  <title>Python 3.14 released</title>
  <link>https://python.example/3.14</link>
  <pubDate>Sun, 09 Nov 2026 08:30:00 GMT</pubDate>
  <description>What's new in Python</description>
</item>
</channel></rss>
"""

HN_PAYLOAD = {
    "hits": [
        {
            "objectID": "1",
            "title": "Show HN: A tiny LLM agent framework",
            "url": "https://github.com/acme/tiny-agent",
            "points": 250,
            "created_at_i": 1762416000,
        },
        {"objectID": "2", "title": "Ask HN: Best Python books?", "url": None, "points": 5, "created_at_i": 1762502400},
        {"objectID": "3", "url": "https://example.com/no-title", "points": 99, "created_at_i": 1762502400},
    ]
}


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, content: bytes):
        self._content = content

    def get(self, url, headers=None, timeout=None):
        return _FakeResponse(self._content)


class _FakeJsonClient(_FakeClient):
    def get(self, url, headers=None, timeout=None):
        import json

        return _FakeResponse(json.dumps(HN_PAYLOAD).encode("utf-8"))


def test_rss_adapter_parses_atom_entries():
    items = RssAdapter("https://example.com/feed", client=_FakeClient(ATOM_FEED.encode())).fetch()
    assert len(items) == 1  # 无 link 的条目被跳过
    item = items[0]
    assert item.title == "Release 2.0 of Demo Framework"
    assert item.url == "https://example.com/posts/2?utm_source=feed"
    assert item.published_at.tzinfo is not None
    assert item.published_at.utcoffset().total_seconds() == 0
    assert "release" in item.raw_summary and "<" not in item.raw_summary
    assert item.heat_raw == 0.0


def test_rss_adapter_parses_rss20():
    items = RssAdapter("https://python.example/rss", client=_FakeClient(RSS_FEED.encode())).fetch()
    assert len(items) == 1
    assert items[0].title == "Python 3.14 released"
    assert items[0].published_at.year == 2026


def test_hn_adapter_parses_hits():
    items = HackerNewsAdapter(client=_FakeJsonClient(b"")).fetch()
    assert len(items) == 2  # 无标题条目跳过
    first, second = items
    assert first.title.startswith("Show HN")
    assert first.heat_raw == 250.0
    assert first.published_at.tzinfo == timezone.utc
    assert second.url.startswith("https://news.ycombinator.com/item?id=2")  # 无外链回退讨论页


def test_strip_html_limits_length():
    long_text = "a" * 500
    assert len(strip_html(f"<p>{long_text}</p>")) == 300
