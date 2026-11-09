"""T5：daily.dev 与 hotai.news 可用性验证（LIVE 探测 + STATIC）。

同时对比项目已有来源：Hacker News（现有 news_hn 适配器）、GitHub（现有集成）。
daily.dev：公共 GraphQL 是否可无鉴权查询。
hotai.news：站点可达性与内容形态。
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import save_result, Timer

UA = {"User-Agent": "personal-assistant-tv2-probe/0.1"}
out = {}


def dailydev_graphql():
    """daily.dev 公共 GraphQL：最新文章列表。"""
    q = {"query": "{ page: latest { edges { node { id title url createdAt source { name } } } } }"}
    try:
        with Timer() as t:
            with httpx.Client(timeout=20, headers={**UA, "Content-Type": "application/json"}) as c:
                resp = c.post("https://api.daily.dev/graphql", json=q)
        data = resp.json()
        edges = (data.get("data") or {}).get("page", {}).get("edges", [])
        items = [{"title": e["node"]["title"][:60], "url": (e["node"].get("url") or "")[:80],
                  "source": (e["node"].get("source") or {}).get("name", ""),
                  "created": e["node"].get("createdAt", "")[:19]} for e in edges[:5]]
        return {"ok": resp.status_code == 200 and len(edges) > 0,
                "status": resp.status_code, "items": len(edges),
                "auth_required": False, "sample_items": items,
                "elapsed_s": t.seconds,
                "note": "无鉴权公共 GraphQL 可取标题/链接/来源；正文需打开原文"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


def hotai_news():
    for url in ("https://hotai.news/", "https://www.hotai.news/"):
        try:
            with httpx.Client(timeout=15, headers=UA, follow_redirects=True) as c:
                resp = c.get(url)
            if resp.status_code == 200 and len(resp.text) > 500:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "lxml")
                text = soup.get_text(" ", strip=True)
                return {"ok": True, "url": str(resp.url), "status": resp.status_code,
                        "title": (soup.title.get_text(strip=True) if soup.title else "")[:100],
                        "text_sample": text[:300]}
            return {"ok": False, "url": url, "status": resp.status_code}
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:200]
    return {"ok": False, "error": last}


def hn_control():
    """对照：Hacker News 官方 API（现有适配器同源）。"""
    try:
        with httpx.Client(timeout=15, headers=UA) as c:
            resp = c.get("https://hacker-news.firebaseio.com/v0/topstories.json")
        ids = resp.json()[:5]
        item = c.get(f"https://hacker-news.firebaseio.com/v0/item/{ids[0]}.json").json()
        return {"ok": resp.status_code == 200 and isinstance(ids, list),
                "status": resp.status_code, "top_items": len(ids),
                "sample_fields": sorted(item.keys()),
                "note": "HN 为技术资讯，非 AI 专项；与本项目现有适配器一致"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


def github_blog_rss():
    """对照：GitHub 官方博客 RSS。"""
    try:
        import feedparser
        with httpx.Client(timeout=15, headers=UA) as c:
            resp = c.get("https://github.blog/feed/")
        feed = feedparser.parse(resp.content)
        return {"ok": resp.status_code == 200 and len(feed.entries) > 0,
                "items": len(feed.entries),
                "sample": [{"title": e.get("title", "")[:60], "link": e.get("link", "")[:70]}
                           for e in feed.entries[:3]]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


out["dailydev_graphql"] = dailydev_graphql()
print("dailydev", out["dailydev_graphql"].get("ok"))
out["hotai_news"] = hotai_news()
print("hotai", out["hotai_news"].get("ok"))
out["hn_control"] = hn_control()
print("hn", out["hn_control"].get("ok"))
out["github_blog_rss"] = github_blog_rss()
print("github_blog", out["github_blog_rss"].get("ok"))

save_result("t5_dailydev_hotai", out)
print("T5 probe done")
