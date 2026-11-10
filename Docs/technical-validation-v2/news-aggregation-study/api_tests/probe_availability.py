# -*- coding: utf-8 -*-
"""候选新闻源可用性探针：记录 URL、状态码、耗时、内容类型、数据量。
运行：D:/miniconda/envs/agent/python.exe probe_availability.py
不修改任何正式业务代码/数据库；仅发起公开 HTTP 请求。
"""
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "results" / "availability.json"
UA = {"User-Agent": "personal-hub-validation/1.0 (+study only, no crawl)"}
CST = timezone(timedelta(hours=8))

CASES = [
    # ---- 国内 ----
    ("remoshuang_home", "GET", "https://remoshuang.com/", {}),
    ("remoshuang_www", "GET", "https://www.remoshuang.com/", {}),
    ("remoshuang_rss", "GET", "https://remoshuang.com/rss", {}),
    ("remoshuang_feed", "GET", "https://remoshuang.com/feed", {}),
    ("remoshuang_api", "GET", "https://remoshuang.com/api", {}),
    ("chinanews_rss_scroll", "GET", "https://www.chinanews.com.cn/rss/scroll-news.xml", {}),
    ("chinanews_rss_yaowen", "GET", "https://www.chinanews.com.cn/rss/yaowen.xml", {}),
    ("chinanews_rss_gn", "GET", "https://www.chinanews.com.cn/rss/gn.xml", {}),
    ("chinanews_rss_sh", "GET", "https://www.chinanews.com.cn/rss/sh.xml", {}),
    ("chinanews_rss_cj", "GET", "https://www.chinanews.com.cn/rss/cj.xml", {}),
    ("chinanews_rss_world", "GET", "https://www.chinanews.com.cn/rss/world.xml", {}),
    ("juhe_docs_dailybrief", "GET", "https://www.juhe.cn/docs", {}),
    ("juhe_simple_nokey", "GET", "https://v.juhe.cn/toutiao/index", {"params": {"type": "guoji", "key": ""}}),
    # ---- 国际 ----
    ("gnews_top_nokey", "GET", "https://gnews.io/api/v4/top-headlines", {"params": {"category": "world", "lang": "en", "max": 5}}),
    ("gnews_search_nokey", "GET", "https://gnews.io/api/v4/search", {"params": {"q": "china", "lang": "en", "max": 5}}),
    ("gnews_docs", "GET", "https://gnews.io/docs/", {}),
    ("bbc_world_rss", "GET", "https://feeds.bbci.co.uk/news/world/rss.xml", {}),
    ("bbc_top_rss", "GET", "https://feeds.bbci.co.uk/news/rss.xml", {}),
    # ---- 复测 GDELT（上轮已可用） ----
    ("gdelt_v2_cn_48h", "GET",
     "https://api.gdeltproject.org/api/v2/doc/doc",
     {"params": {"query": "*", "mode": "artlist", "maxrecords": 20, "format": "json",
                 "timespan": "48h", "sourcelang": "chinese"}}),
    ("gdelt_v2_en_48h", "GET",
     "https://api.gdeltproject.org/api/v2/doc/doc",
     {"params": {"query": "*", "mode": "artlist", "maxrecords": 20, "format": "json",
                 "timespan": "48h", "sourcelang": "english"}}),
]


def probe(name, method, url, extra):
    rec = {"url": url, "method": method}
    t0 = time.perf_counter()
    try:
        r = requests.request(method, url, timeout=20, headers=UA,
                             allow_redirects=True, **extra)
        rec["status"] = r.status_code
        rec["elapsed_s"] = round(time.perf_counter() - t0, 3)
        rec["content_type"] = r.headers.get("Content-Type", "")
        rec["final_url"] = r.url
        rec["bytes"] = len(r.content)
        body = r.text
        rec["head_text"] = body[:300]
        if "json" in rec["content_type"] or body.lstrip().startswith(("{", "[")):
            try:
                j = r.json()
                rec["json_type"] = type(j).__name__
                if isinstance(j, dict):
                    rec["json_keys"] = list(j.keys())[:20]
                    for k in ("articles", "items", "result", "data", "feed"):
                        v = j.get(k)
                        if isinstance(v, list):
                            rec["list_field"] = k
                            rec["list_len"] = len(v)
                            if v:
                                rec["first_item_keys"] = list(v[0].keys())[:20] if isinstance(v[0], dict) else str(v[0])[:100]
                if isinstance(j, list):
                    rec["list_len"] = len(j)
            except Exception as e:  # noqa: BLE001
                rec["json_error"] = f"{type(e).__name__}: {e}"
        elif "<rss" in body[:500] or "<feed" in body[:500]:
            rec["looks_like_feed"] = True
    except requests.exceptions.SSLError as e:
        rec["error"] = f"SSLError: {e}"[:300]
        rec["elapsed_s"] = round(time.perf_counter() - t0, 3)
    except requests.exceptions.ConnectTimeout as e:
        rec["error"] = f"ConnectTimeout: {e}"[:300]
        rec["elapsed_s"] = round(time.perf_counter() - t0, 3)
    except requests.exceptions.ConnectionError as e:
        rec["error"] = f"ConnectionError: {e}"[:300]
        rec["elapsed_s"] = round(time.perf_counter() - t0, 3)
    except requests.exceptions.Timeout as e:
        rec["error"] = f"Timeout: {e}"[:300]
        rec["elapsed_s"] = round(time.perf_counter() - t0, 3)
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
        rec["elapsed_s"] = round(time.perf_counter() - t0, 3)
    return rec


def main():
    now_cst = datetime.now(CST)
    out = {
        "probe": "availability",
        "run_at_cst": now_cst.isoformat(timespec="seconds"),
        "tz": "Asia/Shanghai",
        "note": "所有请求不携带任何 API Key；无 Key 接口的预期错误响应同样记录。",
        "results": {},
    }
    for name, method, url, extra in CASES:
        out["results"][name] = probe(name, method, url, extra)
        print(f"[{name}] status={out['results'][name].get('status')} "
              f"err={out['results'][name].get('error', '')[:60]} "
              f"t={out['results'][name]['elapsed_s']}s")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
