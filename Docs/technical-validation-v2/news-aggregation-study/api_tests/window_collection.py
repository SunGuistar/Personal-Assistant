# -*- coding: utf-8 -*-
"""24 小时固定窗口回溯采集：对 chinanews RSS / GDELT / remoshuang 采集
窗口 2026-11-09 08:00 CST ~ 2026-11-10 08:00 CST（UTC 2026-11-09T00:00Z ~ 2026-11-10T00:00Z）
原始响应存 fixtures/，统计存 results/window_collection.json。
运行：D:/miniconda/envs/agent/python.exe window_collection.py
"""
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests

BASE = Path(__file__).resolve().parent.parent
FIX = BASE / "fixtures"
RES = BASE / "results" / "window_collection.json"
UA = {"User-Agent": "personal-hub-validation/1.0 (+study only)"}
CST = timezone(timedelta(hours=8))

WIN_START = datetime(2026, 11, 9, 8, 0, tzinfo=CST)   # 含
WIN_END = datetime(2026, 11, 10, 8, 0, tzinfo=CST)    # 不含
W0, W1 = WIN_START.astimezone(timezone.utc), WIN_END.astimezone(timezone.utc)


def in_window(dt):
    return dt is not None and W0 <= dt.astimezone(timezone.utc) < W1


def fetch_chinanews(tag, url):
    t0 = time.perf_counter()
    r = requests.get(url, timeout=20, headers=UA)
    elapsed = round(time.perf_counter() - t0, 3)
    raw = r.content
    (FIX / f"chinanews_{tag}_raw.xml").write_bytes(raw)
    f = feedparser.parse(raw)
    items = []
    for e in f.entries:
        dts = e.get("published_parsed") or e.get("updated_parsed")
        dt = datetime(*dts[:6], tzinfo=timezone.utc) if dts else None
        items.append({
            "title": e.get("title", ""),
            "link": e.get("link", ""),
            "published_utc": dt.isoformat() if dt else None,
            "in_window": in_window(dt) if dt else None,
            "summary_len": len(e.get("summary", "") or ""),
        })
    in_w = [i for i in items if i["in_window"]]
    rec = {
        "url": url, "status": r.status_code, "elapsed_s": elapsed,
        "content_type": r.headers.get("Content-Type", ""),
        "feed_title": f.feed.get("title", ""), "total_items": len(items),
        "in_window": len(in_w),
        "earliest_utc": min((i["published_utc"] for i in items if i["published_utc"]), default=None),
        "latest_utc": max((i["published_utc"] for i in items if i["published_utc"]), default=None),
        "sample_items": items[:8],
    }
    return rec, items


def fetch_gdelt(tag, params, note=""):
    """GDELT 带 429 退避重试；保存原始 JSON。"""
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    last = None
    for attempt in range(4):
        t0 = time.perf_counter()
        try:
            r = requests.get(url, params=params, timeout=40, headers=UA)
            elapsed = round(time.perf_counter() - t0, 3)
            if r.status_code == 429:
                wait = 15 * (attempt + 1)
                last = {"status": 429, "retry_in_s": wait}
                time.sleep(wait)
                continue
            (FIX / f"gdelt_{tag}_raw.json").write_bytes(r.content)
            rec = {"params": params, "status": r.status_code, "elapsed_s": elapsed,
                   "note": note, "content_type": r.headers.get("Content-Type", "")}
            try:
                j = r.json()
                arts = j.get("articles", [])
                rec["articles"] = len(arts)
                rec["sample"] = [{k: a.get(k) for k in ("title", "domain", "seendate", "url")} for a in arts[:5]]
                items = [{
                    "title": a.get("title", ""), "url": a.get("url", ""),
                    "domain": a.get("domain", ""), "language": a.get("language", ""),
                    "seendate": a.parse(a.get("seendate", ""), "%Y%m%dT%H%M%SZ") if a.get("seendate") else None,
                } for a in arts]
                rec["in_window"] = sum(1 for it in items if it["seendate"] and in_window(it["seendate"]))
                rec["earliest_seendate"] = min((it["seendate"] for it in items if it["seendate"]), default=None)
                rec["latest_seendate"] = max((it["seendate"] for it in items if it["seendate"]), default=None)
                for it in items:
                    if it["seendate"]:
                        it["seendate"] = it["seendate"].isoformat()
            except Exception as e:  # noqa: BLE001
                rec["parse_error"] = f"{type(e).__name__}: {e}"
                rec["head"] = r.text[:200]
            return rec
        except Exception as e:  # noqa: BLE001
            last = {"error": f"{type(e).__name__}: {e}"[:200]}
            time.sleep(5)
    return {"params": params, "note": note, "failed": last}


def fetch_remoshuang_daily():
    """从 sitemap-daily 找 11-09/11-10 的事件页，抽样解析事件结构。"""
    rec = {"sitemap": None, "events_sampled": []}
    r = requests.get("https://remoshuang.com/sitemap-daily.xml", timeout=20, headers=UA)
    (FIX / "remoshuang_sitemap_daily.xml").write_bytes(r.content)
    rec["sitemap_status"] = r.status_code
    import re
    urls = re.findall(r"<loc>([^<]+)</loc>", r.text)
    day_urls = [u for u in urls if "2026-11-09" in u or "2026-11-10" in u]
    rec["event_urls_for_window_days"] = len(day_urls)
    rec["event_url_sample"] = day_urls[:6]
    # 解析事件页 Nuxt payload（复用探针逻辑）
    for u in day_urls[:4]:
        try:
            html = requests.get(u, timeout=20, headers=UA).text
            scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
            big = max(scripts, key=len)
            arr = json.loads(big)

            def resolve(i, depth=0):
                v = arr[i]
                if isinstance(v, dict):
                    return {k: (resolve(x, depth + 1) if isinstance(x, int) and x < len(arr) and depth < 6 else x)
                            for k, x in v.items()}
                if isinstance(v, list):
                    return [resolve(x, depth + 1) if isinstance(x, int) and x < len(arr) and depth < 6 else x for x in v]
                return v

            # event 对象通常在 {"success":..,"event":N,"related":..} 里
            ev = None
            for v in arr:
                if isinstance(v, dict) and "event" in v and "success" in v:
                    ei = v["event"]
                    if isinstance(ei, int) and ei < len(arr):
                        ev = resolve(ei)
                    break
            if ev:
                rec["events_sampled"].append({
                    "url": u,
                    "date": ev.get("date"), "title": ev.get("title"),
                    "event_url": ev.get("url"),
                    "createdAt": ev.get("createdAt"), "firstSeenAt": ev.get("firstSeenAt"),
                    "category": ev.get("category"), "hotScore": ev.get("hotScore"),
                    "position": ev.get("position"),
                    "sourceCount": ev.get("sourceCount"),
                    "sources": [{k: s.get(k) for k in ("sourceName", "originalUrl", "capturedAt")}
                                for s in ev.get("sources", [])[:5]],
                })
        except Exception as e:  # noqa: BLE001
            rec["events_sampled"].append({"url": u, "error": f"{type(e).__name__}: {e}"[:150]})
    return rec


def main():
    out = {
        "probe": "window_collection",
        "run_at_cst": datetime.now(CST).isoformat(timespec="seconds"),
        "window_cst": {"start_inclusive": WIN_START.isoformat(), "end_exclusive": WIN_END.isoformat()},
        "window_utc": {"start": W0.isoformat(), "end": W1.isoformat()},
    }

    # chinanews：滚动 + 国际，各采两次看条目轮换
    out["chinanews_scroll_r1"], items1 = fetch_chinanews("scroll_r1", "https://www.chinanews.com.cn/rss/scroll-news.xml")
    out["chinanews_world_r1"], _ = fetch_chinanews("world_r1", "https://www.chinanews.com.cn/rss/world.xml")
    time.sleep(3)
    out["chinanews_scroll_r2"], items2 = fetch_chinanews("scroll_r2", "https://www.chinanews.com.cn/rss/scroll-news.xml")
    links1 = {i["link"] for i in items1}
    links2 = {i["link"] for i in items2}
    out["chinanews_stability"] = {
        "r1_total": len(items1), "r2_total": len(items2),
        "overlap_links": len(links1 & links2),
        "r1_only": len(links1 - links2), "r2_only": len(links2 - links1),
    }

    # GDELT：精确起止 vs timespan 语义对照
    out["gdelt_cn_exact"] = fetch_gdelt("cn_exact", {
        "query": "*", "mode": "artlist", "maxrecords": 75, "format": "json",
        "startdatetime": "20261109000000", "enddatetime": "20261110000000",
        "sourcelang": "chinese", "sort": "hybridrel"}, note="chinese exact window")
    out["gdelt_en_exact"] = fetch_gdelt("en_exact", {
        "query": "*", "mode": "artlist", "maxrecords": 75, "format": "json",
        "startdatetime": "20261109000000", "enddatetime": "20261110000000",
        "sourcelang": "english", "sort": "hybridrel"}, note="english exact window")
    out["gdelt_cn_timespan"] = fetch_gdelt("cn_timespan", {
        "query": "*", "mode": "artlist", "maxrecords": 20, "format": "json",
        "timespan": "24h", "sourcelang": "chinese"}, note="chinese timespan 24h rolling (control)")

    # remoshuang 每日事件页
    out["remoshuang_daily"] = fetch_remoshuang_daily()

    FIX.mkdir(parents=True, exist_ok=True)
    RES.parent.mkdir(parents=True, exist_ok=True)
    RES.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "remoshuang_daily"},
                     ensure_ascii=False, indent=1, default=str)[:3000])
    print("remoshuang_daily urls:", out["remoshuang_daily"].get("event_urls_for_window_days"))
    print(f"written -> {RES}")


if __name__ == "__main__":
    sys.exit(main())
