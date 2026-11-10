# -*- coding: utf-8 -*-
"""重大事件覆盖率测量：对人工参考清单中的每个事件，在各候选源采集的 fixture 中检索命中。
运行：D:/miniconda/envs/agent/python.exe coverage_hits.py
输出：results/coverage_hits.json
"""
import csv
import io
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FIX = BASE / "fixtures"
OUT = BASE / "results" / "coverage_hits.json"
CST = timezone(timedelta(hours=8))

W0 = datetime(2026, 11, 9, 8, 0, tzinfo=CST)
W1 = datetime(2026, 11, 10, 8, 0, tzinfo=CST)

EVENTS = {
    "D1": {"group": "domestic", "any": [["太原", "火灾"], ["太原", "14人"]]},
    "D2": {"group": "domestic", "any": [["境外清算"], ["清算行", "外汇"]]},
    "D3": {"group": "domestic", "any": [["统计局", "普查司"], ["国情国力"]]},
    "D4": {"group": "domestic", "any": [["星云星座"], ["太空算力"], ["太空云"]]},
    "I1": {"group": "international", "any": [["APEC"], ["铁门"], ["习近平", "普京"]]},
    "I2": {"group": "international", "any": [["油价"], ["原油", "跌"]]},
    "I3": {"group": "international", "any": [["俄副外长"], ["无意进攻"]]},
    "I4": {"group": "international", "any": [["鲁比奥"], ["黄仁勋"]]},
    "I5": {"group": "international", "any": [["霍尔木兹"], ["袭船"]]},
}


def match(text, spec):
    for group in spec["any"]:
        if all(k in text for k in group):
            return True
    return False


def parse_chinanews_archive(path, date_cst):
    """解析按日归档页，返回 [(datetime_cst, title, link)]"""
    html = path.read_text(encoding="utf-8", errors="ignore")
    items = []
    for li in re.findall(r"<li[^>]*>(.*?)</li>", html, re.S):
        m = re.search(r"(\d{1,2}:\d{2})", li)
        a = re.search(r'href="([^"]*?/2026/11-\d{2}/[^"]+?\.shtml)"[^>]*>(.*?)</a>', li, re.S)
        if not (m and a):
            continue
        title = re.sub(r"<[^>]+>", "", a.group(2)).strip()
        hh, mm = m.group(1).split(":")
        dt = datetime.strptime(f"{date_cst} {hh}:{mm}", "%Y-%m-%d %H:%M").replace(tzinfo=CST)
        items.append((dt, title, a.group(1)))
    return items


def parse_remoshuang_md(path):
    text = path.read_text(encoding="utf-8")
    items = []
    for m in re.finditer(r"\d+\.\s+\[([^\]]+)\]\(([^)]+)\)", text):
        items.append(m.group(1).strip(), ) if False else items.append((m.group(1).strip(), m.group(2)))
    return items, text


def parse_remoshuang_feed(path):
    import feedparser
    f = feedparser.parse(path.read_bytes())
    return [(e.get("title", ""), e.get("link", ""), e.get("summary", "") or "") for e in f.entries]


def parse_gdelt_csv(path):
    if not path.exists():
        return []
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    out = []
    for r in rows:
        sd = r.get("seendate", "")
        try:
            dt = datetime.strptime(sd, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(CST)
        except ValueError:
            dt = None
        out.append((dt, r.get("title", ""), r.get("url", ""), r.get("domain", "")))
    return out


def main():
    sources = {}

    # chinanews 归档（两日合并，按窗口过滤）
    arch = []
    for day, f in [("2026-11-09", "chinanews_archive_20261109.html"),
                   ("2026-11-10", "chinanews_archive_20261110.html")]:
        p = FIX / f
        if p.exists():
            arch += parse_chinanews_archive(p, day)
    in_window = [(dt, t, u) for dt, t, u in arch if dt and W0 <= dt < W1]
    sources["chinanews_archive"] = {
        "total_parsed": len(arch), "in_window": len(in_window),
        "items": [{"time_cst": dt.isoformat(), "title": t, "link": u} for dt, t, u in in_window],
    }

    # chinanews RSS（scroll/world，采集于 13:40 CST，窗口外）
    for tag, f in [("chinanews_rss_scroll", "chinanews_scroll_r1_raw.xml"),
                   ("chinanews_rss_world", "chinanews_world_r1_raw.xml")]:
        import feedparser
        fp = feedparser.parse((FIX / f).read_bytes())
        sources[tag] = {"items": [{"title": e.get("title", ""), "link": e.get("link", ""),
                                   "published": e.get("published", "")} for e in fp.entries]}

    # remoshuang
    items, fulltext = parse_remoshuang_md(FIX / "remoshuang_daily_2026-11-10.md")
    sources["remoshuang_daily_md"] = {"items": [{"title": t, "link": u} for t, u in items],
                                      "fulltext_len": len(fulltext)}
    items2, _ = parse_remoshuang_md(FIX / "remoshuang_hot_2026-11-10.md")
    sources["remoshuang_hot_md"] = {"items": [{"title": t, "link": u} for t, u in items2]}
    sources["remoshuang_feed"] = {"items": [{"title": t, "link": u, "summary": s[:200]}
                                            for t, u, s in parse_remoshuang_feed(FIX / "remoshuang_feed_xml.xml")]}

    # GDELT
    sources["gdelt_cn_window"] = {"items": [{"seendate_cst": dt.isoformat() if dt else None,
                                             "title": t, "url": u, "domain": d}
                                            for dt, t, u, d in parse_gdelt_csv(FIX / "gdelt_cn_window_raw.csv")]}
    sources["gdelt_en_window"] = {"items": [{"seendate_cst": dt.isoformat() if dt else None,
                                             "title": t, "url": u, "domain": d}
                                            for dt, t, u, d in parse_gdelt_csv(FIX / "gdelt_en_window_raw.csv")]}

    # 命中测量
    hits = {}
    for ev, spec in EVENTS.items():
        hits[ev] = {"group": spec["group"]}
        for src, data in sources.items():
            found = []
            for it in data["items"]:
                text = it["title"] + " " + it.get("summary", "")
                if match(text, spec):
                    found.append(it)
            hits[ev][src] = {"hit": bool(found), "matches": found[:3]}
        # 全文匹配（针对 daily md 的正文摘要）
        if "fulltext_len" in sources["remoshuang_daily_md"]:
            pass

    summary = {}
    for src in sources:
        covered = [ev for ev in EVENTS if hits[ev][src]["hit"]]
        summary[src] = {"domestic_hits": [e for e in covered if EVENTS[e]["group"] == "domestic"],
                        "international_hits": [e for e in covered if EVENTS[e]["group"] == "international"]}

    out = {"measured_at_cst": datetime.now(CST).isoformat(timespec="seconds"),
           "window_cst": {"start": W0.isoformat(), "end_exclusive": W1.isoformat()},
           "note": "关键词命中仅表示该源含相关条目，是否属于窗口内仍以各源时间字段为准；"
                   "GDELT 若 fixture 缺失说明该次采集失败。",
           "hits": hits, "summary": summary}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"written -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
