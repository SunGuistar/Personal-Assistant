"""T10：阶段缓存与局部重算验证（SIMULATION）。

四种缓存机制分离验证：
1. LangGraph Checkpoint（流程状态恢复）
2. 12 小时阶段结果缓存（成功节点复用，输入哈希匹配）
3. 服务商 Prompt Token 缓存（观测字段，不控制逻辑）
4. Embedding 复用缓存（见 t22）

场景：
- 相同输入复用（执行次数不增）
- 资讯/个人记录/Memory/模型/Prompt版本/改写配置 变化 → 对应阶段失效
- 人工强制失效
- 全量重算
- 进程重启后缓存恢复（SQLite 持久化）
- 12 小时有效期
- 每日 08:00 清理上一轮（不触及长期数据）
- 重新生成时主编与事实校验必须重新执行
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import save_result

BJ = timezone(timedelta(hours=8))
db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
con = sqlite3.connect(db)
con.execute("""CREATE TABLE stage_cache (
    stage TEXT, input_hash TEXT, result TEXT, model_ver TEXT, prompt_ver TEXT,
    rag_conf TEXT, created_at TEXT, expires_at TEXT, PRIMARY KEY (stage, input_hash))""")
con.execute("""CREATE TABLE long_term (kind TEXT, key TEXT, value TEXT,
              PRIMARY KEY (kind, key))""")  # 长期新闻/晨报/Memory/日志/费用
con.commit()

stats = {"compute": 0, "reuse": 0, "invalidations": []}


def h(**parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def run_stage(stage, inputs, compute_fn, force=False, must_recompute=False):
    """阶段执行：命中且未过期→复用；否则计算并缓存。主编/校验例外：must_recompute。"""
    key = h(stage=stage, **inputs)
    now = datetime.now(BJ)
    row = con.execute("SELECT result, expires_at FROM stage_cache WHERE stage=? AND input_hash=?",
                      (stage, key)).fetchone()
    if row and not force and not must_recompute:
        exp = datetime.fromisoformat(row[1])
        if exp > now:
            stats["reuse"] += 1
            return {"result": json.loads(row[0]), "from_cache": True}
    stats["compute"] += 1
    result = compute_fn()
    con.execute("INSERT OR REPLACE INTO stage_cache VALUES (?,?,?,?,?,?,?,?)",
                (stage, key, json.dumps(result, ensure_ascii=False),
                 inputs.get("model_ver", ""), inputs.get("prompt_ver", ""),
                 inputs.get("rag_conf", ""), now.isoformat(),
                 (now + timedelta(hours=12)).isoformat()))
    con.commit()
    return {"result": result, "from_cache": False}


out = {"scenarios": {}}
NEWS = {"hash": "news_v1"}
PERSONAL = {"hash": "personal_v1"}
MEMORY = {"hash": "memory_v1"}

# S1 相同输入复用
r1 = run_stage("news_analysis", {"news": NEWS["hash"], "personal": PERSONAL["hash"],
                                 "memory": MEMORY["hash"], "model_ver": "m1", "prompt_ver": "p1"},
               lambda: {"summary": "资讯分析结果A"})
r2 = run_stage("news_analysis", {"news": NEWS["hash"], "personal": PERSONAL["hash"],
                                 "memory": MEMORY["hash"], "model_ver": "m1", "prompt_ver": "p1"},
               lambda: {"summary": "资讯分析结果A"})
out["scenarios"]["S1_same_input_reuse"] = (r2["from_cache"] and stats["compute"] == 1)

# S2 资讯变化 → 资讯分析失效（但个人分析输入不含 news → 可复用）
NEWS["hash"] = "news_v2"
r3 = run_stage("news_analysis", {"news": NEWS["hash"], "personal": PERSONAL["hash"],
                                 "memory": MEMORY["hash"], "model_ver": "m1", "prompt_ver": "p1"},
               lambda: {"summary": "资讯分析结果B"})
pa1 = run_stage("personal_analysis", {"personal": PERSONAL["hash"], "memory": MEMORY["hash"],
                                      "model_ver": "m1", "prompt_ver": "p1"},
                lambda: {"summary": "个人分析结果A"})
pa2 = run_stage("personal_analysis", {"personal": PERSONAL["hash"], "memory": MEMORY["hash"],
                                      "model_ver": "m1", "prompt_ver": "p1"},
                lambda: {"summary": "个人分析结果A"})
out["scenarios"]["S2_news_change_local_invalidate"] = (not r3["from_cache"] and pa2["from_cache"])

# S3 个人记录变化 → 个人分析失效
PERSONAL["hash"] = "personal_v2"
pa3 = run_stage("personal_analysis", {"personal": PERSONAL["hash"], "memory": MEMORY["hash"],
                                      "model_ver": "m1", "prompt_ver": "p1"},
                lambda: {"summary": "个人分析结果B"})
out["scenarios"]["S3_personal_change_invalidate"] = not pa3["from_cache"]

# S4 Memory 变化 → 依赖 Memory 的阶段失效
MEMORY["hash"] = "memory_v2"
pa4 = run_stage("personal_analysis", {"personal": PERSONAL["hash"], "memory": MEMORY["hash"],
                                      "model_ver": "m1", "prompt_ver": "p1"},
                lambda: {"summary": "个人分析结果C"})
out["scenarios"]["S4_memory_change_invalidate"] = not pa4["from_cache"]

# S5 模型版本变化 → 失效
pa5 = run_stage("personal_analysis", {"personal": PERSONAL["hash"], "memory": MEMORY["hash"],
                                      "model_ver": "m2", "prompt_ver": "p1"},
                lambda: {"summary": "个人分析结果D"})
out["scenarios"]["S5_model_change_invalidate"] = not pa5["from_cache"]

# S6 Prompt 版本变化 → 失效
pa6 = run_stage("personal_analysis", {"personal": PERSONAL["hash"], "memory": MEMORY["hash"],
                                      "model_ver": "m2", "prompt_ver": "p2"},
                lambda: {"summary": "个人分析结果E"})
out["scenarios"]["S6_prompt_change_invalidate"] = not pa6["from_cache"]

# S7 Query 改写/Rerank 配置变化 → 使用该配置的检索型阶段失效
ra1 = run_stage("tech_research", {"news": NEWS["hash"], "rag_conf": "rw0_rr0"},
                lambda: {"findings": "研究结论v1"})
ra2 = run_stage("tech_research", {"news": NEWS["hash"], "rag_conf": "rw1_rr0"},
                lambda: {"findings": "研究结论v2"})
out["scenarios"]["S7_rag_conf_change_invalidate"] = not ra2["from_cache"]

# S8 人工强制失效
key8 = h(stage="personal_analysis", personal=PERSONAL["hash"], memory=MEMORY["hash"],
         model_ver="m2", prompt_ver="p2")
con.execute("DELETE FROM stage_cache WHERE stage='personal_analysis' AND input_hash=?", (key8,))
con.commit()
pa7 = run_stage("personal_analysis", {"personal": PERSONAL["hash"], "memory": MEMORY["hash"],
                                      "model_ver": "m2", "prompt_ver": "p2"},
                lambda: {"summary": "个人分析结果F"})
out["scenarios"]["S8_manual_invalidate"] = not pa7["from_cache"]

# S9 全量重算（force）
n_before = stats["compute"]
run_stage("news_analysis", {"news": NEWS["hash"], "personal": PERSONAL["hash"],
                            "memory": MEMORY["hash"], "model_ver": "m1", "prompt_ver": "p1"},
          lambda: {"summary": "x"}, force=True)
out["scenarios"]["S9_full_recompute"] = stats["compute"] == n_before + 1

# S10 进程重启后恢复
con.close()
con = sqlite3.connect(db)
pa8 = run_stage("personal_analysis", {"personal": PERSONAL["hash"], "memory": MEMORY["hash"],
                                      "model_ver": "m2", "prompt_ver": "p2"},
                lambda: {"summary": "should not run"})
out["scenarios"]["S10_survive_restart"] = pa8["from_cache"] and pa8["result"]["summary"] == "个人分析结果F"

# S11 12 小时有效期（伪造过期时间）
con.execute("UPDATE stage_cache SET expires_at=? WHERE stage='personal_analysis'",
            ((datetime.now(BJ) - timedelta(minutes=1)).isoformat(),))
con.commit()
pa9 = run_stage("personal_analysis", {"personal": PERSONAL["hash"], "memory": MEMORY["hash"],
                                      "model_ver": "m2", "prompt_ver": "p2"},
                lambda: {"summary": "个人分析结果G"})
out["scenarios"]["S11_12h_expiry"] = not pa9["from_cache"]

# S12 每日 08:00 清理上一轮阶段缓存（不触及长期数据）
con.execute("INSERT OR REPLACE INTO long_term VALUES ('memory','m1','用户偏好'),"
            "('report','rpt-1','晨报版本'),('log','run-1','执行日志'),('cost','c1','费用')")
lt_before = con.execute("SELECT COUNT(*) FROM long_term").fetchone()[0]
con.execute("DELETE FROM stage_cache")  # 08:00 清理
lt_after = con.execute("SELECT COUNT(*) FROM long_term").fetchone()[0]
out["scenarios"]["S12_0800_cleanup_keeps_long_term"] = (lt_before == lt_after == 4)

# S13 重新生成：主编与事实校验必须重新执行（must_recompute）
ed1 = run_stage("editor", {"all": "same"}, lambda: {"report": "正文"}, must_recompute=True)
ed2 = run_stage("editor", {"all": "same"}, lambda: {"report": "正文2"}, must_recompute=True)
vf = run_stage("fact_verify", {"report": h(report="正文2")}, lambda: {"ok": True},
               must_recompute=True)
out["scenarios"]["S13_editor_verify_always_rerun"] = (
    not ed1["from_cache"] and not ed2["from_cache"] and not vf["from_cache"])

out["four_caches_distinction"] = {
    "langgraph_checkpoint": "图执行状态/断点恢复（t15 验证）",
    "stage_cache_12h": "成功节点结果复用，本轮验证",
    "provider_prompt_cache": "服务商计费/加速字段（t8：prompt_cache_hit_tokens 实测返回）",
    "embedding_cache": "向量复用（t22 验证，独立于 12h 清理）",
}
out["stats"] = stats
out["db_temp"] = db
con.close()
save_result("t10_stage_cache", out)
print("T10 done:", json.dumps(out["scenarios"], ensure_ascii=False))
print("stats:", stats)
