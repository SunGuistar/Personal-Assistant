# -*- coding: utf-8 -*-
"""热摸爽（remoshuang.com）结构探针：抓取 / 与 /rss 页面，提取疑似数据接口与 RSS 地址。
运行：D:/miniconda/envs/agent/python.exe probe_remoshuang.py
"""
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "results" / "remoshuang_structure.json"
UA = {"User-Agent": "personal-hub-validation/1.0 (+study only, no crawl)"}
CST = timezone(timedelta(hours=8))

CANDIDATE_PATHS = [
    "/api/hot", "/api/hot-list", "/api/hotlist", "/api/rank", "/api/hot-rank",
    "/api/v1/hot", "/api/feed", "/api/feeds", "/api/rss", "/api/hotspot",
    "/rss.xml", "/feed.xml", "/atom.xml", "/sitemap.xml", "/robots.txt",
    "/api/v1/rank", "/api/hot_board", "/api/boards",
]


def fetch(path):
    url = "https://remoshuang.com" + path
    t0 = time.perf_counter()
    rec = {"url": url}
    try:
        r = requests.get(url, timeout=15, headers=UA)
        rec["status"] = r.status_code
        rec["elapsed_s"] = round(time.perf_counter() - t0, 3)
        rec["content_type"] = r.headers.get("Content-Type", "")
        rec["bytes"] = len(r.content)
        body = r.text
        rec["head"] = body[:200]
        if "json" in rec["content_type"]:
            try:
                j = r.json()
                rec["json_keys"] = list(j.keys())[:30] if isinstance(j, dict) else f"list[{len(j)}]"
            except Exception as e:  # noqa: BLE001
                rec["json_error"] = str(e)[:120]
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"[:200]
        rec["elapsed_s"] = round(time.perf_counter() - t0, 3)
    return rec


def main():
    out = {"probe": "remoshuang_structure", "run_at_cst": datetime.now(CST).isoformat(timespec="seconds"),
           "page_links": [], "page_endpoints": [], "path_probes": {}}

    for path in ["/", "/rss"]:
        r = requests.get("https://remoshuang.com" + path, timeout=15, headers=UA)
        html = r.text
        hrefs = set(re.findall(r'href="([^"#]+)"', html))
        srcs = set(re.findall(r'(?:src|action)="([^"]+)"', html))
        apis = set(re.findall(r'["\'](/api/[^"\']{2,60})["\']', html))
        rss_like = {h for h in hrefs | srcs if re.search(r'\.xml\b|/rss|/feed|/atom', h)}
        out["page_links"] += sorted(h for h in hrefs if h.startswith("/") and len(h) < 60)[:80]
        out["page_endpoints"] += sorted(apis)
        out.setdefault("rss_like", [])
        out["rss_like"] += sorted(rss_like)

    out["page_links"] = sorted(set(out["page_links"]))
    out["page_endpoints"] = sorted(set(out["page_endpoints"]))
    out["rss_like"] = sorted(set(out["rss_like"]))

    for p in CANDIDATE_PATHS:
        rec = fetch(p)
        out["path_probes"][p] = rec
        print(p, rec.get("status"), rec.get("content_type", "")[:30], rec.get("error", "")[:40])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
