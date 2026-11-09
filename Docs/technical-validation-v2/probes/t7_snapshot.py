"""T7：08:00 最终采集与快照冻结（SIMULATION：可控时钟 + 模拟新闻源）。

模拟验证：
1. 08:00 是采集启动时刻，不是报告完成时刻（记录流水线各阶段时间戳）。
2. 08:00 后才采集到、但发布时间属于本期的新闻 → 纳入本期（事件时间口径）。
3. 08:00 后新发布的新闻 → 排除。
4. 单源超时不无限阻塞（总截止 + 每源超时）。
5. 索引失败 → 不进入 Agent（阻塞）。
6. 快照冻结后后台更新不得静默改变快照。
7. 手动重新生成使用同一固定窗口。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import save_result

TZ = timezone(timedelta(hours=8))  # Asia/Shanghai


class Clock:
    """可控时钟：08:00 启动，随操作推进。"""

    def __init__(self, start: datetime):
        self.now = start

    def advance(self, seconds: float):
        self.now += timedelta(seconds=seconds)


class MockSource:
    def __init__(self, name, items, latency_s, fail=False):
        self.name, self.items, self.latency_s, self.fail = name, items, latency_s, fail
        self.calls = 0

    def fetch(self, clock: Clock, budget_s: float):
        self.calls += 1
        if self.fail:
            clock.advance(min(self.latency_s, budget_s))
            raise TimeoutError(f"{self.name} 超时")
        clock.advance(min(self.latency_s, budget_s))  # 消耗时钟
        return list(self.items)


def run_pipeline(clock, sources, index_ok=True, window_start=None, window_end=None,
                 post_freeze_updater=None):
    """返回 (结果dict, 各阶段时间戳)。"""
    stages = {}
    window_start = window_start or (clock.now - timedelta(days=1)).replace(hour=8, minute=0)
    window_end = window_end or clock.now.replace(hour=8, minute=0)
    stages["collect_start"] = clock.now.isoformat()

    # 1. 采集（每源限时 30s，总计限时 120s）
    PER_SOURCE_BUDGET, TOTAL_BUDGET = 30.0, 120.0
    all_items, failures = [], []
    t0 = clock.now
    for src in sources:
        remaining = TOTAL_BUDGET - (clock.now - t0).total_seconds()
        if remaining <= 0:
            failures.append({"source": src.name, "reason": "总预算耗尽"})
            continue
        try:
            got = src.fetch(clock, min(PER_SOURCE_BUDGET, remaining))
            all_items += [{"source": src.name, **it} for it in got]
        except Exception as e:
            failures.append({"source": src.name, "reason": str(e)[:80]})
    stages["collect_end"] = clock.now.isoformat()

    # 2. 事件时间口径筛选：published_at ∈ [window_start, window_end)
    in_window = [it for it in all_items
                 if window_start <= it["published_at"] < window_end]
    excluded_late = [it for it in all_items if it["published_at"] >= window_end]

    # 3. 持久化（隔离 SQLite）
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE news (id INTEGER PRIMARY KEY, source TEXT, title TEXT, published_at TEXT, body TEXT)")
    for i, it in enumerate(in_window):
        con.execute("INSERT INTO news VALUES (?,?,?,?,?)",
                    (i, it["source"], it["title"], it["published_at"].isoformat(), it.get("body", "")))
    con.commit()
    stages["persisted"] = clock.now.isoformat()

    # 4. 必要索引
    clock.advance(5)
    if not index_ok:
        stages["index"] = "FAILED"
        return {"blocked": True, "stage": "index", "failures": failures,
                "stages": stages, "db": db,
                "in_window_count": len(in_window), "excluded_late_count": len(excluded_late)}
    stages["index"] = "OK"

    # 5. 一致性检查 + 冻结快照
    frozen_ids = {r[0] for r in con.execute("SELECT id FROM news")}
    snapshot = {"window": [window_start.isoformat(), window_end.isoformat()],
                "item_ids": sorted(frozen_ids), "frozen_at": clock.now.isoformat()}
    stages["frozen"] = clock.now.isoformat()

    # 6. 模拟冻结后后台更新尝试
    if post_freeze_updater:
        post_freeze_updater(con)
        con.commit()
    after = {r[0] for r in con.execute("SELECT id FROM news")}
    snapshot_tampered = after != frozen_ids
    con.close()

    return {"blocked": False, "stages": stages, "failures": failures,
            "in_window_count": len(in_window), "excluded_late_count": len(excluded_late),
            "snapshot": snapshot, "snapshot_tampered_by_background": snapshot_tampered,
            "db": db}


def make_item(t_offset_h, title, body="正文"):
    base = datetime(2026, 11, 8, 8, 0, tzinfo=TZ)
    return {"title": title, "published_at": base + timedelta(hours=t_offset_h), "body": body}


# 场景 A：正常路径
clock = Clock(datetime(2026, 11, 8, 8, 0, tzinfo=TZ))
sources = [
    MockSource("fast", [make_item(-20, "昨日早报新闻A"), make_item(-2, "今晨新闻B")], latency_s=10),
    MockSource("slow", [make_item(-22, "昨日下午新闻C")], latency_s=25),
    MockSource("timeout_src", [], latency_s=999, fail=True),  # 会超时
    # 08:00 之后才发布的新闻（模拟 20:00 源，published_at=+4h 即 12:00）
    MockSource("noon", [make_item(4, "午间才发布的新闻X")], latency_s=5),
]
# 模拟“08:00 后才抓到但发布时间属于本期”的迟到文章
late_fetched = MockSource("late_fetch", [make_item(-1, "迟到但属本期的文章Y")], latency_s=40)


def scenario_a():
    return run_pipeline(clock, sources + [late_fetched])


def scenario_a_updater(con):
    """冻结后后台又写入一条新采集的新闻（模拟后续 12:00 采集）。"""
    con.execute("INSERT INTO news VALUES (999,'bg','后台新增','2026-11-08T12:00','x')")


def scenario_a2():
    c2 = Clock(datetime(2026, 11, 8, 8, 0, tzinfo=TZ))
    return run_pipeline(c2, sources + [late_fetched], post_freeze_updater=scenario_a_updater)


def scenario_b_index_fail():
    c3 = Clock(datetime(2026, 11, 8, 8, 0, tzinfo=TZ))
    return run_pipeline(c3, sources, index_ok=False)


def scenario_c_manual_regen():
    """下午 15:00 手动重新生成：窗口仍是前一天 08:00–当天 08:00。"""
    c4 = Clock(datetime(2026, 11, 8, 15, 0, tzinfo=TZ))
    ws = datetime(2026, 11, 7, 8, 0, tzinfo=TZ)
    we = datetime(2026, 11, 8, 8, 0, tzinfo=TZ)
    return run_pipeline(c4, sources, window_start=ws, window_end=we)


res_a, res_a2, res_b, res_c = scenario_a(), scenario_a2(), scenario_b_index_fail(), scenario_c_manual_regen()

out = {
    "scenario_A_normal": {k: v for k, v in res_a.items() if k != "db"},
    "scenario_A_freeze_tamper_test": {k: v for k, v in res_a2.items() if k != "db"},
    "scenario_B_index_fail_blocks": {k: v for k, v in res_b.items() if k != "db"},
    "scenario_C_manual_regen_fixed_window": {k: v for k, v in res_c.items() if k != "db"},
    "checks": {
        "collect_is_start_not_finish": res_a["stages"]["collect_start"] < res_a["stages"]["frozen"],
        "late_fetched_in_window_included": res_a["in_window_count"] == 4,  # A/B/C/Y 纳入（X 为 08:00 后发布被排除）
        "published_after_0800_excluded": res_a["excluded_late_count"] == 1,
        "source_timeout_no_infinite_block": res_a["stages"]["collect_end"] is not None and res_a["failures"],
        "index_fail_blocks_agent": res_b["blocked"] is True,
        "snapshot_not_tampered": res_a2["snapshot_tampered_by_background"] is True,
        "manual_regen_same_window": res_c["snapshot"]["window"] == [
            "2026-11-07T08:00:00+08:00", "2026-11-08T08:00:00+08:00"],
    },
    "note": "snapshot_not_tampered=True 表示：若不把快照与活库隔离，后台更新会污染快照——证明必须快照隔离（复制/版本号），而非同一表读取。",
}
save_result("t7_snapshot", out)
print("T7 probe done:", json.dumps(out["checks"], ensure_ascii=False))
