"""第三轮网络探测：修正解析逻辑（baidu/zhihu JSON 结构、daily.dev introspection、GDELT 重试）。"""
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
        print(name, "->", r.get("ok"))
    except Exception as e:
        out[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:250]}
        print(name, "-> ERROR", str(e)[:120])


def baidu_top():
    with httpx.Client(timeout=15, headers=UA) as c:
        resp = c.get("https://top.baidu.com/api/board",
                     params={"platform": "wise", "tab": "realtime"})
    data = resp.json()
    cards = (data.get("data") or {}).get("cards") or []
    items = []
    for card in cards:
        items.extend(card.get("content", []))
    if not items:  # 结构变化兜底：直接看 data 键
        return {"ok": False, "status": resp.status_code,
                "data_keys": list((data.get("data") or {}).keys())[:10],
                "raw_head": resp.text[:200]}
    it = items[0]
    return {"ok": len(items) > 5, "status": resp.status_code, "hot_items": len(items),
            "first_item_keys": sorted(it.keys()),
            "sample": [{"word": i.get("word", ""), "hot_score": i.get("hot_score"),
                        "raw_url": (i.get("raw_url") or i.get("url") or "")[:60]}
                       for i in items[:6]]}


def zhihu_hot():
    with httpx.Client(timeout=15, headers={**UA, "Referer": "https://www.zhihu.com/"}) as c:
        resp = c.get("https://www.zhihu.com/api/v3/feed/topstory/hot-list-web",
                     params={"limit": 10, "desktop": "true"})
    data = resp.json()
    items = data.get("data", [])
    targets = [(it.get("target") or {}) for it in items]
    return {"ok": resp.status_code == 200 and len(items) > 0,
            "status": resp.status_code, "items": len(items),
            "target_keys": sorted(targets[0].keys()) if targets else [],
            "sample_titles": [t.get("title", "")[:30] for t in targets[:6]],
            "has_excerpt": bool(targets and targets[0].get("excerpt"))}


def dailydev_introspect():
    q = "{ __type(name: \"Query\") { fields { name args { name } } } }"
    with httpx.Client(timeout=20, headers={**UA, "Content-Type": "application/json"}) as c:
        resp = c.post("https://api.daily.dev/graphql", json={"query": q})
    data = resp.json()
    fields = [f["name"] for f in ((data.get("data") or {}).get("__type") or {}).get("fields", [])]
    return {"ok": len(fields) > 0, "status": resp.status_code, "query_fields": fields[:40]}


def gdelt_retry():
    url = ("https://api.gdeltproject.org/api/v2/doc/doc"
           "?query=china&mode=artlist&maxrecords=20&format=json&timespan=24h")
    with httpx.Client(timeout=40, headers=UA) as c:
        resp = c.get(url)
    ct = resp.headers.get("content-type", "")
    if "json" not in ct:
        return {"ok": False, "status": resp.status_code, "content_type": ct,
                "body_head": resp.text[:300]}
    data = resp.json()
    arts = data.get("articles", [])
    return {"ok": len(arts) > 0, "status": resp.status_code, "items": len(arts),
            "sample": [{"title": a.get("title", "")[:40], "domain": a.get("domain", ""),
                        "seendate": a.get("seendate", "")} for a in arts[:6]],
            "fields": sorted(arts[0].keys()) if arts else []}


def chinanews_detail():
    import feedparser
    with httpx.Client(timeout=12, headers=UA) as c:
        feed = feedparser.parse(c.get("https://www.chinanews.com.cn/rss/scroll-news.xml").content)
    e = feed.entries[0]
    return {"ok": len(feed.entries) > 0, "items": len(feed.entries),
            "sample": {"title": e.get("title", "")[:50], "link": e.get("link", "")[:80],
                       "published": str(e.get("published", ""))[:40],
                       "summary_len": len(e.get("summary", ""))},
            "has_full_content": False,
            "note": "RSS 提供标题/链接/时间/短摘要；正文需回溯原站抓取"}


run("baidu_top_board_v2", baidu_top)
run("zhihu_hot_v2", zhihu_hot)
run("dailydev_introspect", dailydev_introspect)
run("gdelt_retry", gdelt_retry)
run("chinanews_rss_detail", chinanews_detail)

save_result("net_round3", out)
print("round3 done")
