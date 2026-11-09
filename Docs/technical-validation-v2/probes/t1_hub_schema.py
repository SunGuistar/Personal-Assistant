"""T1：原个人助手数据库（hub.db）历史数据可用性（只读审计）。

方法：
- 只读连接（mode=ro），仅输出聚合统计与字段映射，不导出个人内容。
- 验证“前一天 08:00 – 当天 08:00”窗口事件可否还原：
  daily_tasks 完成事件（completed_at）、创建事件（created_at）、
  长期计划状态变化（updated_at/completed_at/is_important）、GitHub 活动（authored_at）。
- 静态核查 services/plans_service.py 中 completed_at 的写入/清除语义。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import save_result

DB = "file:E:/wechat-LangGraph/data/hub.db?mode=ro"
con = sqlite3.connect(DB, uri=True)
cur = con.cursor()
out = {}


def agg(sql, *args):
    return cur.execute(sql, args).fetchall()


# ---- daily_tasks：完成事件可还原性 ----
total, done_cnt = agg("SELECT COUNT(*), SUM(done) FROM daily_tasks")[0]
done_with_ct, done_null_ct = agg(
    "SELECT SUM(CASE WHEN completed_at IS NOT NULL AND completed_at<>'' THEN 1 ELSE 0 END),"
    " SUM(CASE WHEN completed_at IS NULL OR completed_at='' THEN 1 ELSE 0 END)"
    " FROM daily_tasks WHERE done=1")[0]
undone_with_ct = agg("SELECT COUNT(*) FROM daily_tasks WHERE done=0 AND completed_at IS NOT NULL AND completed_at<>''")[0][0]
# completed_at 与 task_date 不一致的比例（完成时间≠任务日 → 有真实完成时间证据）
mismatch = agg(
    "SELECT COUNT(*) FROM daily_tasks WHERE done=1 AND completed_at IS NOT NULL"
    " AND substr(completed_at,1,10) <> task_date")[0][0]
mm_sample = agg(
    "SELECT task_date, substr(completed_at,1,16) FROM daily_tasks WHERE done=1 AND completed_at IS NOT NULL"
    " AND substr(completed_at,1,10) <> task_date LIMIT 5")
same_day = agg(
    "SELECT COUNT(*) FROM daily_tasks WHERE done=1 AND completed_at IS NOT NULL"
    " AND substr(completed_at,1,10) = task_date")[0][0]
created_dist = agg("SELECT MIN(created_at), MAX(created_at), MIN(updated_at), MAX(updated_at) FROM daily_tasks")[0]
window_test = agg(
    "SELECT COUNT(*) FROM daily_tasks WHERE completed_at IS NOT NULL"
    " AND completed_at >= '2026-11-06 08:00' AND completed_at < '2026-11-07 08:00'")[0][0]

out["daily_tasks"] = {
    "total": total, "done": done_cnt,
    "done_with_completed_at": done_with_ct,
    "done_without_completed_at": done_null_ct,
    "undone_but_has_completed_at": undone_with_ct,
    "done_completed_on_task_date": same_day,
    "done_completed_off_task_date": mismatch,
    "off_task_date_samples_masked": mm_sample,  # 仅日期/时间，无内容
    "created_at_range": created_dist,
    "window_query_test_2026-11-06T08:00_to_2026-11-07T08:00_completed_events": window_test,
}

# ---- long_term_plans ----
plans = agg("SELECT status, COUNT(*) FROM long_term_plans GROUP BY status")
important = agg("SELECT COUNT(*) FROM long_term_plans WHERE is_important=1")[0][0]
plan_ct = agg("SELECT COUNT(*) FROM long_term_plans WHERE completed_at IS NOT NULL AND completed_at<>''")[0][0]
plan_range = agg("SELECT MIN(created_at), MAX(updated_at) FROM long_term_plans")[0]
out["long_term_plans"] = {"by_status": plans, "is_important_count": important,
                          "with_completed_at": plan_ct, "time_range": plan_range}

# ---- GitHub 活动 ----
gh = {}
for t, col in [("github_commits", "authored_at"), ("github_pull_requests", "created_at"),
               ("github_issues", "created_at")]:
    n = agg(f"SELECT COUNT(*) FROM {t}")[0][0]
    rng = agg(f"SELECT MIN({col}), MAX({col}) FROM {t}")[0]
    gh[t] = {"count": n, f"{col}_range": rng}
gh["commits_window_test"] = agg(
    "SELECT COUNT(*) FROM github_commits WHERE authored_at >= '2026-11-06 08:00' AND authored_at < '2026-11-07 08:00'")[0][0]
out["github"] = gh

# ---- memos / important_infos / reading：只有 created/updated ----
for t in ["memos", "important_infos", "books", "book_notes"]:
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})")]
    n = agg(f"SELECT COUNT(*) FROM {t}")[0][0]
    has_ct = "completed_at" in cols
    out[t] = {"count": n, "has_completed_at": has_ct,
              "time_fields": [c for c in cols if "at" in c or "date" in c]}

# ---- 既有去重/费用/状态机先例 ----
out["precedents"] = {
    "news_items_count": agg("SELECT COUNT(*) FROM news_items")[0][0],
    "news_items_has_title_hash": [r[1] for r in cur.execute("PRAGMA table_info(news_items)") if r[1] == "title_hash"] != [],
    "token_usage_count": agg("SELECT COUNT(*) FROM token_usage")[0][0],
    "tasks_state_machine_rows": agg("SELECT COUNT(*) FROM tasks")[0][0],
}
con.close()

# ---- 静态核查：completed_at 语义 ----
svc = Path(r"E:/wechat-LangGraph/app/services/plans_service.py").read_text(encoding="utf-8")
import re
hits = [ln.strip()[:120] for ln in svc.splitlines() if "completed_at" in ln]
out["static_completed_at_semantics"] = hits

save_result("t1_hub_schema", out)
print("T1 probe done")
