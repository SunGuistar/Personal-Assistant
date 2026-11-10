# -*- coding: utf-8 -*-
"""GDELT 固定窗口重试（低频、CSV 格式、429 退避）+ 保存 remoshuang 冻结快照 fixture。
运行：D:/miniconda/envs/agent/python.exe gdelt_window_retry.py
"""
import csv
import io
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
FIX = BASE / "fixtures"
RES = BASE / "results" / "gdelt_window.json"
UA = {"User-Agent": "personal-hub-validation/1.0 (+study only)"}
CST = timezone(timedelta(hours=8))
W0 = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)   # 2026-11-09 08:00 CST
W1 = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)  # 2026-11-10 08:00 CST


def gdelt(tag, params, attempts=5):
    rec = {"params": params}
    for i in range(attempts):
        time.sleep(20 if i else 0)
        t0 = time.perf_counter()
        try:
            r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc",
                             params=params, timeout=90, headers=UA)
            rec["status"] = r.status_code
            rec["elapsed_s"] = round(time.perf_counter() - t0, 2)
            rec["content_type"] = r.headers.get("Content-Type", "")
            if r.status_code == 429:
                rec["retry_wait_s"] = 30 * (i + 1)
                time.sleep(rec["retry_wait_s"])
                continue
            text = r.text
            (FIX / f"gdelt_{tag}_raw.csv").write_text(text, encoding="utf-8")
            rows = list(csv.DictReader(io.StringIO(text)))
            rec["articles"] = len(rows)
            rec["fields"] = list(rows[0].keys()) if rows else []
            in_w, times = 0, []
            for row in rows:
                sd = row.get("seendate", "")
                try:
                    dt = datetime.strptime(sd, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                times.append(dt)
                if W0 <= dt < W1:
                    in_w += 1
            rec["in_window_by_seendate"] = in_w
            rec["earliest_seendate"] = min(times).isoformat() if times else None
            rec["latest_seendate"] = max(times).isoformat() if times else None
            rec["sample"] = [{k: row.get(k) for k in ("title", "domain", "seendate", "url")}
                             for row in rows[:5]]
            return rec
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
    return rec


def save_remoshuang_fixtures():
    rec = {}
    for tag, url in [
        ("daily_2026-11-10", "https://remoshuang.com/daily/2026-11-10.md"),
        ("daily_2026-11-09", "https://remoshuang.com/daily/2026-11-09.md"),
        ("hot_2026-11-10", "https://remoshuang.com/hot/2026-11-10.md"),
        ("feed_xml", "https://remoshuang.com/feed.xml"),
        ("agents_page", "https://remoshuang.com/agents"),
    ]:
        r = requests.get(url, timeout=20, headers=UA)
        name = url.rstrip("/").split("/")[-1] or "index"
        suffix = ".md" if url.endswith(".md") else (".xml" if url.endswith(".xml") else ".html")
        (FIX / f"remoshuang_{tag}{suffix}").write_bytes(r.content)
        rec[tag] = {"status": r.status_code, "bytes": len(r.content)}
    return rec


def main():
    FIX.mkdir(parents=True, exist_ok=True)
    out = {"probe": "gdelt_window", "run_at_cst": datetime.now(CST).isoformat(timespec="seconds"),
           "window_utc": {"start": W0.isoformat(), "end": W1.isoformat()}}
    out["remoshuang_fixtures"] = save_remoshuang_fixtures()
    out["gdelt_cn"] = gdelt("cn_window", {
        "query": "*", "mode": "artlist", "maxrecords": 75, "format": "csv",
        "startdatetime": "20261109000000", "enddatetime": "20261110000000",
        "sourcelang": "chinese", "sort": "hybridrel"})
    out["gdelt_en"] = gdelt("en_window", {
        "query": "*", "mode": "artlist", "maxrecords": 75, "format": "csv",
        "startdatetime": "20261109000000", "enddatetime": "20261110000000",
        "sourcelang": "english", "sort": "hybridrel"})
    RES.parent.mkdir(parents=True, exist_ok=True)
    RES.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:2500])
    print(f"written -> {RES}")


if __name__ == "__main__":
    sys.exit(main())
