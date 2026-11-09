"""T3：国际社会资讯源验证（BBC 为主）（LIVE 探测）。

验证：RSS 连通性、字段（标题/时间/链接/摘要）、时区、更新延迟、
正文获取能力（抓取一条真实文章页解析正文）、使用限制说明。
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import save_result, Timer

UA = {"User-Agent": "personal-assistant-tv2-probe/0.1 (personal news reader)"}
out = {}

FEEDS = {
    "bbc_world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc_top": "https://feeds.bbci.co.uk/news/rss.xml",
    "cnn_world": "http://rss.cnn.com/rss/edition_world.rss",
    "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}


def fetch_feed(name, url):
    r = {"url": url}
    try:
        with Timer() as t:
            with httpx.Client(timeout=20, headers=UA) as c:
                resp = c.get(url)
        r["elapsed_s"] = t.seconds
        r["status"] = resp.status_code
        if resp.status_code != 200:
            r["ok"] = False
            return r
        import feedparser
        feed = feedparser.parse(resp.content)
        entries = feed.entries[:10]
        r["feed_title"] = getattr(feed.feed, "title", "")
        r["items"] = len(feed.entries)
        # 字段完整性与时区
        tzs = set()
        dates = []
        for e in entries:
            dt = None
            for attr in ("published_parsed", "updated_parsed"):
                p = getattr(e, attr, None)
                if p:
                    dt = datetime(*p[:6], tzinfo=timezone.utc)
                    break
            if dt:
                dates.append(dt)
                tzs.add("UTC-normalized")
        r["time_fields_ok"] = len(dates) == len(entries)
        r["sample_times"] = [d.isoformat()[:19] for d in dates[:3]]
        r["has_link"] = all(getattr(e, "link", "") for e in entries)
        r["has_summary"] = sum(1 for e in entries if getattr(e, "summary", ""))
        r["ok"] = r["items"] > 0
        # 更新延迟：最新条目距现在多久
        if dates:
            newest = max(dates)
            r["newest_item_age_minutes"] = round((datetime.now(timezone.utc) - newest).total_seconds() / 60, 1)
    except Exception as e:
        r["ok"] = False
        r["error"] = f"{type(e).__name__}: {e}"[:300]
    return r


for name, url in FEEDS.items():
    out[name] = fetch_feed(name, url)
    print(name, out[name].get("ok"))

# 正文获取：抓 BBC 第一条文章页
body_test = {}
try:
    with httpx.Client(timeout=20, headers=UA) as c:
        feed = __import__("feedparser").parse(c.get(FEEDS["bbc_world"]).content)
        link = feed.entries[0].link
        with Timer() as t:
            page = c.get(link)
        soup = BeautifulSoup(page.text, "lxml")
        # BBC 正文主要在 article 的 p 标签
        paras = [p.get_text(" ", strip=True) for p in soup.select("article p")]
        paras = [p for p in paras if len(p) > 40]
        text = "\n".join(paras)
        body_test = {"ok": page.status_code == 200 and len(text) > 500,
                     "status": page.status_code, "article_url": link[:100],
                     "extracted_chars": len(text), "paragraphs": len(paras),
                     "elapsed_s": t.seconds,
                     "headline": (soup.title.get_text(strip=True)[:80] if soup.title else ""),
                     "method": "httpx + BeautifulSoup(article p)",
                     "license_note": "BBC 内容受版权与 ToS 约束；RSS 描述为摘要，全文仅个人阅读用途需评估"}
except Exception as e:
    body_test = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
out["bbc_fulltext_extraction"] = body_test
print("bbc_fulltext", body_test.get("ok"))

save_result("t3_intl_sources", out)
print("T3 probe done")
