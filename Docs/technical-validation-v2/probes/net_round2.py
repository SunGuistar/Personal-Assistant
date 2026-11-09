"""第二轮网络探测：修正第一轮的问题并补充国内来源（LIVE）。

- GDELT：放宽查询（仅 sourcelang:chinese + timespan）。
- 澎湃新闻：跟随 302 看落点。
- daily.dev：尝试多种 GraphQL 查询形状。
- HN：修复 client 关闭 bug。
- 新增国内来源：百度热搜榜 API、知乎热榜、中新网 RSS 尝试、新华网首页。
- NewsAPI：无 key 端点连通性（异常也要记录）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import save_result, Timer

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) personal-assistant-tv2-probe/0.1"}
out = {}


def run(name, fn):
    try:
        with Timer() as t:
            r = fn()
        r["elapsed_s"] = t.seconds
        out[name] = r
        print(name, "->", r.get("ok"), r.get("status", ""))
    except Exception as e:
        out[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:250]}
        print(name, "-> ERROR", e)


def gdelt_simple():
    url = ("https://api.gdeltproject.org/api/v2/doc/doc"
           "?query=sourcelang:chinese&mode=artlist&maxrecords=25&format=json&timespan=48h")
    with httpx.Client(timeout=30, headers=UA) as c:
        resp = c.get(url)
    data = resp.json()
    arts = data.get("articles", [])
    return {"ok": resp.status_code == 200 and len(arts) > 0, "status": resp.status_code,
            "items": len(arts),
            "sample_masked": [{"title": a.get("title", "")[:40], "domain": a.get("domain", ""),
                               "seendate": a.get("seendate", "")} for a in arts[:8]],
            "fields": sorted(arts[0].keys()) if arts else [],
            "has_body": False}


def thepaper_follow():
    with httpx.Client(timeout=15, headers=UA, follow_redirects=True) as c:
        resp = c.get("https://www.thepaper.cn/rss.xml")
    return {"ok": resp.status_code == 200, "status": resp.status_code,
            "final_url": str(resp.url), "bytes": len(resp.text),
            "looks_like_rss": "<rss" in resp.text[:500] or "<feed" in resp.text[:500]}


def dailydev_try_queries():
    shapes = {
        "simple_latest": "{ latest { edges { node { id title url } } } }",
        "with_type": "{ page: latest { edges { node { ... on Article { id title url createdAt source { name } } } } } }",
        "ping": "{ query { source(id: \"daily\") { id name } } }",
    }
    results = {}
    with httpx.Client(timeout=20, headers={**UA, "Content-Type": "application/json"}) as c:
        for name, q in shapes.items():
            try:
                resp = c.post("https://api.daily.dev/graphql", json={"query": q})
                data = resp.json()
                edges = (data.get("data") or {}).get("page", {}).get("edges") or \
                        (data.get("data") or {}).get("latest", {}).get("edges")
                results[name] = {"status": resp.status_code,
                                 "errors": data.get("errors"),
                                 "edge_count": len(edges) if edges else 0}
                if edges:
                    n = edges[0]["node"]
                    results[name]["sample"] = {k: str(v)[:60] for k, v in n.items()}
            except Exception as e:
                results[name] = {"error": str(e)[:150]}
    ok_any = any(r.get("edge_count", 0) > 0 for r in results.values())
    return {"ok": ok_any, "queries": results}


def hn_fixed():
    with httpx.Client(timeout=15, headers=UA) as c:
        resp = c.get("https://hacker-news.firebaseio.com/v0/topstories.json")
        ids = resp.json()[:5]
        item = c.get(f"https://hacker-news.firebaseio.com/v0/item/{ids[0]}.json").json()
    return {"ok": resp.status_code == 200, "status": resp.status_code,
            "sample_fields": sorted(item.keys()),
            "sample_title": item.get("title", "")[:60]}


def baidu_top():
    with httpx.Client(timeout=15, headers=UA) as c:
        resp = c.get("https://top.baidu.com/api/board",
                     params={"platform": "wise", "tab": "realtime"})
    data = resp.json()
    cards = (data.get("data") or {}).get("cards") or []
    items = []
    for card in cards:
        items += card.get("content", [])[:5]
    return {"ok": resp.status_code == 200 and len(items) > 0, "status": resp.status_code,
            "boards": [c.get("tabName", "") for c in cards],
            "hot_items": len(items),
            "sample": [{"word": i.get("word", "")[:30], "hot_score": i.get("hot_score", ""),
                        "url": (i.get("url") or "")[:60]} for i in items[:5]],
            "fields": sorted(items[0].keys()) if items else []}


def zhihu_hot():
    with httpx.Client(timeout=15, headers={**UA, "Referer": "https://www.zhihu.com/"}) as c:
        resp = c.get("https://www.zhihu.com/api/v3/feed/topstory/hot-list-web",
                     params={"limit": 10, "desktop": "true"})
    data = resp.json()
    items = data.get("data", [])
    return {"ok": resp.status_code == 200 and len(items) > 0, "status": resp.status_code,
            "items": len(items),
            "sample": [(it.get("target") or {}).get("title_part", "")[:30] for it in items[:5]]}


def chinanews_rss():
    import feedparser
    for url in ("https://www.chinanews.com.cn/rss/scroll-news.xml",
                "https://www.chinanews.com.cn/rss/yaowen.xml"):
        try:
            with httpx.Client(timeout=12, headers=UA) as c:
                resp = c.get(url)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
                return {"ok": len(feed.entries) > 0, "status": resp.status_code, "url": url,
                        "items": len(feed.entries)}
        except Exception:
            continue
    return {"ok": False, "status": "unreachable/404"}


def xinhuanet_home():
    with httpx.Client(timeout=15, headers=UA) as c:
        resp = c.get("https://www.news.cn/")
    return {"ok": resp.status_code == 200, "status": resp.status_code}


def newsapi_connectivity():
    try:
        with httpx.Client(timeout=15) as c:
            resp = c.get("https://newsapi.org/v2/top-headlines",
                         params={"country": "cn", "apiKey": "invalid-tv2-probe"})
        return {"endpoint_reachable": True, "status": resp.status_code,
                "error_body_masked": {k: v for k, v in resp.json().items()
                                      if k in ("status", "code", "message")}}
    except Exception as e:
        return {"endpoint_reachable": False, "error": f"{type(e).__name__}: {e}"[:150]}


run("gdelt_simple", gdelt_simple)
run("thepaper_follow", thepaper_follow)
run("dailydev_queries", dailydev_try_queries)
run("hn_fixed", hn_fixed)
run("baidu_top_board", baidu_top)
run("zhihu_hot", zhihu_hot)
run("chinanews_rss", chinanews_rss)
run("xinhuanet_home", xinhuanet_home)
out["newsapi_connectivity"] = newsapi_connectivity()
print("newsapi ->", out["newsapi_connectivity"].get("endpoint_reachable"))

save_result("net_round2", out)
print("round2 done")
