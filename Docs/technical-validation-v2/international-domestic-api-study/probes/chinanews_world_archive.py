# -*- coding: utf-8 -*-
"""中新网按日归档页：国际新闻识别与 08:00-08:00 窗口提取验证。

抓取 2026-11-09 与 2026-11-10 两个归档页，解析每条新闻的栏目/标题/URL/发布时间，
过滤窗口 [2026-11-09 08:00, 2026-11-10 08:00)（北京时间），统计国际栏目条目数，
并验证：国际新闻能否从归档页可靠识别、时间戳精度、跨两天窗口拼接。

原始 HTML 存 fixtures/，统计存 results/chinanews_world_window.json。
运行：python probes/chinanews_world_archive.py
"""
import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
FIX = BASE / "fixtures"
RES = BASE / "results" / "chinanews_world_window.json"
UA = {"User-Agent": "personal-hub-validation/1.0 (+study only)"}
CST = timezone(timedelta(hours=8))

WIN_START = datetime(2026, 11, 9, 8, 0, tzinfo=CST)
WIN_END = datetime(2026, 11, 10, 8, 0, tzinfo=CST)

DAYS = ["2026/1109", "2026/1110"]
URL_TPL = "https://www.chinanews.com.cn/scroll-news/{day}/news.shtml"

# 归档页条目形如：
# <li><div class="dd_lm">[<a href=/world.shtml>国际</a>]</div> <div class="dd_bt">
# <a href="/gj/2026/11-09/10729157.shtml">标题</a></div><div class="dd_time">11-9 23:02</div></li>
LI_RE = re.compile(
    r'<div class="dd_lm">\[<a[^>]*>(?P<cat>[^<]*)</a>\]</div>\s*<div class="dd_bt">'
    r'<a[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a></div>'
    r'<div class="dd_time">(?P<time>\d{1,2}-\d{1,2}\s+\d{2}:\d{2})</div>',
    re.S,
)


def fetch(day):
    url = URL_TPL.format(day=day)
    t0 = time.perf_counter()
    r = requests.get(url, timeout=25, headers=UA)
    elapsed = round(time.perf_counter() - t0, 3)
    tag = day.replace("/", "")
    (FIX / f"chinanews_archive_{tag}.html").write_bytes(r.content)
    r.encoding = r.apparent_encoding or "utf-8"
    items = []
    for m in LI_RE.finditer(r.text):
        cat = m.group("cat").strip()
        mmdd, hhmm = m.group("time").split()
        mo, dd = mmdd.split("-")
        hh, mi = hhmm.split(":")
        # 归档页年份取 URL 中的年份
        year = int(day.split("/")[0])
        dt = datetime(year, int(mo), int(dd), int(hh), int(mi), tzinfo=CST)
        href = m.group("href")
        if href.startswith("/"):
            href = "https://www.chinanews.com.cn" + href
        items.append({
            "category": cat,
            "title": re.sub(r"<[^>]+>", "", m.group("title")).strip(),
            "url": href,
            "published_cst": dt.isoformat(),
            "in_window": WIN_START <= dt < WIN_END,
        })
    return {
        "url": url, "status": r.status_code, "elapsed_s": elapsed,
        "content_type": r.headers.get("Content-Type", ""),
        "total_parsed": len(items),
        "categories": sorted({i["category"] for i in items}),
        "in_window_total": sum(1 for i in items if i["in_window"]),
        "items": items,
    }


def main():
    out = {"window_cst": {"start": WIN_START.isoformat(), "end": WIN_END.isoformat()}, "days": []}
    for d in DAYS:
        rec = fetch(d)
        rec.pop("items", None)
        out["days"].append(rec)
        print(f"{d}: HTTP {rec['status']} parsed={rec['total_parsed']} in_window={rec['in_window_total']}")
        print("  categories:", rec["categories"])

    # 窗口内国际条目（含跨天拼接）
    all_items = []
    for d in DAYS:
        all_items += fetch_items_cached(d)
    win = [i for i in all_items if i["in_window"]]
    intl = [i for i in win if i["category"] == "国际"]
    out["window"] = {
        "all_in_window": len(win),
        "intl_in_window": len(intl),
        "intl_window_earliest": min((i["published_cst"] for i in intl), default=None),
        "intl_window_latest": max((i["published_cst"] for i in intl), default=None),
        "intl_items": [{"title": i["title"], "url": i["url"], "published_cst": i["published_cst"]} for i in intl],
    }
    print(f"窗口内全部条目 {len(win)}，国际栏目 {len(intl)} 条")
    RES.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved:", RES)


def fetch_items_cached(day):
    html = (FIX / f"chinanews_archive_{day.replace('/', '')}.html").read_text(encoding="utf-8", errors="ignore")
    items = []
    year = int(day.split("/")[0])
    for m in LI_RE.finditer(html):
        cat = m.group("cat").strip()
        mmdd, hhmm = m.group("time").split()
        mo, dd = mmdd.split("-")
        hh, mi = hhmm.split(":")
        dt = datetime(year, int(mo), int(dd), int(hh), int(mi), tzinfo=CST)
        href = m.group("href")
        if href.startswith("/"):
            href = "https://www.chinanews.com.cn" + href
        items.append({"category": cat, "title": re.sub(r"<[^>]+>", "", m.group("title")).strip(),
                      "url": href, "published_cst": dt.isoformat(), "in_window": WIN_START <= dt < WIN_END})
    return items


if __name__ == "__main__":
    main()
