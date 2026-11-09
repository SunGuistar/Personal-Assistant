"""T2：国内社会资讯源连通性与可用性（LIVE 探测）。

候选来源（免费/无需新开通付费）：
- GDELT 2.0 Doc API（免费，覆盖中文国内新闻，JSON）
- 澎湃新闻 RSS 尝试、China Daily RSS（英文但涉华）、
- 公开 RSSHub 实例（如可用）
- 新华网/人民网首页可达性（作为抓取可行性参考，非 API）
每个来源记录：可达性、字段完整性（标题/时间/URL/摘要）、时效、正文获取能力。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import save_result, Timer

UA = {"User-Agent": "personal-assistant-tv2-probe/0.1"}
results = {}


def probe(name, fn):
    try:
        with Timer() as t:
            r = fn()
        r["elapsed_s"] = t.seconds
        results[name] = r
        print(f"{name}: {r.get('ok')}")
    except Exception as e:  # 探针脚本允许记录失败
        results[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        print(f"{name}: ERROR {e}")


def gdelt():
    """GDELT：中文+中国 社会新闻，近 24h，JSON artlist。"""
    url = ("https://api.gdeltproject.org/api/v2/doc/doc"
           "?query=(china%20OR%20%E4%B8%AD%E5%9B%BD)%20sourcelang:chinese%20domainis:cn"
           "&mode=artlist&maxrecords=25&format=json&timespan=24h")
    with httpx.Client(timeout=20, headers=UA) as c:
        resp = c.get(url)
        data = resp.json()
    arts = data.get("articles", [])
    fields = set()
    for a in arts[:25]:
        fields |= set(a.keys())
    now = datetime.now(timezone.utc)
    fresh = 0
    for a in arts:
        try:
            seendate = datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            if (now - seendate).total_seconds() < 24 * 3600:
                fresh += 1
        except ValueError:
            pass
    return {"ok": resp.status_code == 200 and len(arts) > 0,
            "status": resp.status_code, "items": len(arts),
            "fields": sorted(fields), "fresh_24h": fresh,
            "has_body": False,  # artlist 只有标题/URL/时间，无正文
            "sample_masked_domains": sorted({a.get("domain", "") for a in arts[:25]})[:10],
            "auth": "免费无 key", "license_note": "GDELT 仅提供元数据与链接，正文需回溯原站"}


def thepaper_rss():
    url = "https://www.thepaper.cn/rss.xml"
    with httpx.Client(timeout=15, headers=UA) as c:
        resp = c.get(url)
    return {"ok": resp.status_code == 200, "status": resp.status_code,
            "content_type": resp.headers.get("content-type", ""),
            "bytes": len(resp.content),
            "note": "需人工确认内容是否为可用 RSS（见 evidence）"}


def chinadaily_rss():
    url = "http://www.chinadaily.com.cn/rss/china_rss.xml"
    import feedparser
    with httpx.Client(timeout=15, headers=UA) as c:
        resp = c.get(url)
    feed = feedparser.parse(resp.content)
    entries = [{"title": e.get("title", "")[:60], "link": e.get("link", "")[:80],
                "published": str(e.get("published", ""))[:40]} for e in feed.entries[:5]]
    return {"ok": resp.status_code == 200 and len(feed.entries) > 0,
            "status": resp.status_code, "items": len(feed.entries),
            "sample_entries": entries, "language": "英文（涉华新闻）"}


def rsshub_thepaper():
    """公开 RSSHub 实例（demo 域），不稳定仅作备选参考。"""
    url = "https://rsshub.app/thepaper/featured"
    try:
        with httpx.Client(timeout=15, headers=UA) as c:
            resp = c.get(url)
        return {"ok": resp.status_code == 200, "status": resp.status_code,
                "bytes": len(resp.content),
                "note": "公共实例稳定性不可保证，仅证明 RSSHub 路线可行" if resp.status_code == 200 else "公共实例不可用"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def xinhuanet_head():
    with httpx.Client(timeout=15, headers=UA) as c:
        resp = c.get("http://www.xinhuanet.com/")
    return {"ok": resp.status_code == 200, "status": resp.status_code,
            "note": "门户首页可达；无官方免费 API，抓取需自研解析+遵守 robots"}


probe("gdelt_v2_cn", gdelt)
probe("thepaper_rss", thepaper_rss)
probe("chinadaily_rss", chinadaily_rss)
probe("rsshub_public", rsshub_thepaper)
probe("xinhuanet_home", xinhuanet_head)

save_result("t2_cn_sources", {"results": results})
print("T2 probe done")
