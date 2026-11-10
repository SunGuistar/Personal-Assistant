# -*- coding: utf-8 -*-
"""国际重大新闻覆盖率测量：独立参考事件清单 × 候选源命中。

窗口：2026-11-09 08:00 ~ 2026-11-10 08:00（北京时间，起点含终点不含）。

参考事件清单（5 件国际事件）复用 news-aggregation-study 的
fixtures/reference_events.json（该清单当时由财新/新华社/朝日·路透/Gulf News/同花顺转央视
等独立来源交叉核实建立，非来自任何本轮候选源）。本轮在其上补充评估：
  - chinanews 归档页窗口内「全部栏目」与「仅国际栏目」两个口径（LIVE，本目录实测）；
  - 热摸爽 daily 2026-11-10（LIVE，本目录实测）；
  - 天聚数行 world / 聚合数据每日简报 / 顺为数据：无 Key，BLOCKED，不参与命中统计。

命中判定：标题关键词命中（脚本自动）+ 人工复核（results 中带 matched_title）。
运行：python probes/coverage_hits.py
"""
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REF = BASE.parent / "news-aggregation-study" / "fixtures" / "reference_events.json"
RES = BASE / "results" / "coverage_hits.json"

EVENTS = {
    "I1": {"kw": ["铁门"], "desc": "特朗普宣布对伊'铁门'行动/APEC 会晤预期"},
    "I2": {"kw": ["油价", "原油"], "desc": "特朗普淡化再袭伊朗，国际油价早盘跌超5%"},
    "I3": {"kw": ["副外长", "无意进攻"], "desc": "俄副外长重申俄无意进攻欧洲国家"},
    "I4": {"kw": ["鲁比奥", "黄仁勋"], "desc": "NYT：鲁比奥曾警告黄仁勋与中国'间谍'关系"},
    "I5": {"kw": ["霍尔木兹"], "desc": "美伊对峙：霍尔木兹海峡袭船频发"},
}


def load_chinanews_window():
    sys.path.insert(0, str(BASE / "probes"))
    from chinanews_world_archive import fetch_items_cached
    items = fetch_items_cached("2026/1109") + fetch_items_cached("2026/1110")
    return [i for i in items if i["in_window"]]


def load_remoshuang():
    t = (BASE / "fixtures" / "remoshuang_daily_2026-11-10.md").read_text(encoding="utf-8")
    return [re.sub(r"<[^>]+>", "", m).strip()
            for m in re.findall(r"^\d+\.\s+\[([^\]]+)\]\([^)]+\)", t, re.M)]


def hit(titles, kws):
    for t in titles:
        if any(k in t for k in kws):
            return t
    return None


def main():
    ref = json.loads(REF.read_text(encoding="utf-8"))
    cn_all = load_chinanews_window()
    cn_intl_titles = [i["title"] for i in cn_all if i["category"] == "国际"]
    cn_all_titles = [i["title"] for i in cn_all]
    rm_titles = load_remoshuang()

    sources = {
        "chinanews_intl_column": {"titles": cn_intl_titles, "n_items": len(cn_intl_titles)},
        "chinanews_all_columns": {"titles": cn_all_titles, "n_items": len(cn_all_titles)},
        "remoshuang_daily": {"titles": rm_titles, "n_items": len(rm_titles)},
        "tianapi_world": {"blocked": "无 API Key，真实数据调用 BLOCKED"},
        "juhe_daily_bulletin": {"blocked": "无 API Key，真实数据调用 BLOCKED"},
        "itapi_news": {"blocked": "无 API Key，真实数据调用 BLOCKED"},
    }
    report = {"window_cst": {"start": "2026-11-09T08:00:00+08:00", "end_exclusive": "2026-11-10T08:00:00+08:00"},
              "reference_provenance": ref["description"],
              "events": [], "summary": {}}
    for eid, e in EVENTS.items():
        row = {"id": eid, "desc": e["desc"], "ref_title": next(
            x["title"] for x in ref["international"] if x["id"] == eid)}
        for name, s in sources.items():
            if "blocked" in s:
                row[name] = {"status": "BLOCKED"}
            else:
                m = hit(s["titles"], e["kw"])
                row[name] = {"status": "HIT" if m else "MISS", "matched_title": m}
        report["events"].append(row)
    for name, s in sources.items():
        if "blocked" in s:
            report["summary"][name] = {"status": "BLOCKED", "note": s["blocked"]}
        else:
            hits = sum(1 for r in report["events"] if r[name]["status"] == "HIT")
            report["summary"][name] = {"hits": hits, "total": len(EVENTS),
                                       "coverage": round(hits / len(EVENTS), 3),
                                       "n_items_in_window": s["n_items"]}
    union = sum(1 for r in report["events"]
                if any(r[n]["status"] == "HIT" for n in
                       ("chinanews_all_columns", "remoshuang_daily")))
    report["summary"]["combination_chinanews_plus_remoshuang"] = {"hits": union, "total": len(EVENTS)}
    RES.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("saved:", RES)


if __name__ == "__main__":
    main()
