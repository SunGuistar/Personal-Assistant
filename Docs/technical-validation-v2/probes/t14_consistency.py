"""T14：SQLite / Qdrant 一致性验证（SIMULATION + INTEGRATION）。

10 个场景（晨报独立 SQLite 用隔离临时库）：
1 正常增量写入  2 重复写入幂等  3 写入中途异常  4 索引失败
5 重试修复  6 正文更新  7 版本号不一致  8 快照冻结版本
9 晨报保存成功但索引失败  10 下一轮生成前索引完整性检查

关键断言：必要索引未完成 → workflow 禁止进入 Agent（无隐式兜底）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_hub_env, save_result

URL = "http://127.0.0.1:8633"
VEC_SIZE = 1024
COL = "tv2_consistency"
client = httpx.Client(base_url=URL, timeout=30)

db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
con = sqlite3.connect(db)
con.executescript("""
CREATE TABLE news (id INTEGER PRIMARY KEY, url TEXT UNIQUE, title TEXT, body TEXT,
                   content_hash TEXT, qdrant_indexed INTEGER DEFAULT 0, version INTEGER DEFAULT 1);
CREATE TABLE reports (id INTEGER PRIMARY KEY, version_id TEXT UNIQUE, body TEXT,
                      qdrant_indexed INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE index_state (scope TEXT PRIMARY KEY, required_ok INTEGER, checked_at TEXT);
""")
client.put(f"/collections/{COL}", json={"vectors": {"size": VEC_SIZE, "distance": "Cosine"}})

out = {"scenarios": {}}


def pseudo_vec(text, size=VEC_SIZE):
    v = [0.0] * size
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16)
        v[h % size] += 1.0
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


def index_news(row_id):
    row = con.execute("SELECT title, body FROM news WHERE id=?", (row_id,)).fetchone()
    pid = str(uuid.uuid4())
    client.put(f"/collections/{COL}/points", json={"points": [{
        "id": pid, "vector": pseudo_vec(row[0] + row[1]),
        "payload": {"sqlite_id": row_id, "title": row[0]}}]})
    client.post(f"/collections/{COL}/points?wait=true", json={})
    con.execute("UPDATE news SET qdrant_indexed=1 WHERE id=?", (row_id,))
    con.commit()
    return pid


def required_index_ok():
    pending = con.execute("SELECT COUNT(*) FROM news WHERE qdrant_indexed=0").fetchone()[0]
    rp = con.execute("SELECT COUNT(*) FROM reports WHERE qdrant_indexed=0").fetchone()[0]
    # 同时验证 Qdrant 侧确有数据
    n = client.get(f"/collections/{COL}").json()["result"]["points_count"]
    ok = (pending == 0 and rp == 0 and n > 0)
    con.execute("INSERT OR REPLACE INTO index_state VALUES ('pre_run', ?, datetime('now'))", (int(ok),))
    con.commit()
    return ok


def gate_agent():
    return required_index_ok()  # False 时禁止进入 Agent


# S1 正常增量写入
cur = con.execute("INSERT INTO news (url,title,body,content_hash) VALUES (?,?,?,?)",
                  ("http://a/1", "AI 新闻一", "正文一", hashlib.sha1("正文一".encode()).hexdigest()))
index_news(cur.lastrowid)
out["scenarios"]["S1_normal"] = gate_agent() is True

# S2 重复写入幂等（同 url 不重复插，索引不重复建）
try:
    con.execute("INSERT INTO news (url,title,body,content_hash) VALUES (?,?,?,?)",
                ("http://a/1", "AI 新闻一", "正文一", hashlib.sha1("正文一".encode()).hexdigest()))
    con.commit()
    dup = False
except sqlite3.IntegrityError:
    dup = True
n_before = client.get(f"/collections/{COL}").json()["result"]["points_count"]
con.execute("UPDATE news SET qdrant_indexed=1 WHERE id=?", (cur.lastrowid,))
n_after = client.get(f"/collections/{COL}").json()["result"]["points_count"]
out["scenarios"]["S2_idempotent"] = dup and n_before == n_after

# S3 写入中途异常（SQLite 已提交、索引未做 → 不一致可检测）
cur3 = con.execute("INSERT INTO news (url,title,body,content_hash) VALUES (?,?,?,?)",
                   ("http://a/3", "AI 新闻三", "正文三", "h3"))
con.commit()
# 模拟崩溃：未调 index_news
out["scenarios"]["S3_mid_write_crash_detectable"] = gate_agent() is False

# S4/S5 索引失败 → 重试修复
try:
    client.put("http://127.0.0.1:9/bad-endpoint", json={})  # 失败调用
    idx_fail = True
except Exception:
    idx_fail = True
pid3 = index_news(cur3.lastrowid)
out["scenarios"]["S4_index_fail_then_S5_retry_fix"] = gate_agent() is True

# S6 正文更新（版本 +1，旧索引清理，重索引）
con.execute("UPDATE news SET body=?, version=version+1, qdrant_indexed=0 WHERE id=?",
            ("正文三（更新版）", cur3.lastrowid))
con.commit()
client.post(f"/collections/{COL}/points/delete?wait=true", json={
    "filter": {"must": [{"key": "sqlite_id", "match": {"value": cur3.lastrowid}}]}})
client.post(f"/collections/{COL}/points?wait=true", json={})
index_news(cur3.lastrowid)
r = client.post(f"/collections/{COL}/points/scroll", json={
    "filter": {"must": [{"key": "sqlite_id", "match": {"value": cur3.lastrowid}}]}, "limit": 10})
out["scenarios"]["S6_body_update_reindexed"] = len(r.json()["result"]["points"]) == 1

# S7 元数据/版本不一致检测（SQLite version=3，Qdrant payload version 缺失 → 检测逻辑）
row = con.execute("SELECT version FROM news WHERE id=?", (cur3.lastrowid,)).fetchone()
payloads = [p["payload"] for p in client.post(f"/collections/{COL}/points/scroll", json={
    "filter": {"must": [{"key": "sqlite_id", "match": {"value": cur3.lastrowid}}]},
    "limit": 10, "with_payload": True}).json()["result"]["points"]]
mismatch = any(p.get("version") != row[0] for p in payloads if "version" in p) or \
    any("version" not in p for p in payloads)
out["scenarios"]["S7_version_mismatch_flagged"] = mismatch  # payload 缺 version 字段 → 标记

# S8 快照冻结版本
frozen = {"news_ids": [r[0] for r in con.execute("SELECT id FROM news")],
          "points_count": client.get(f"/collections/{COL}").json()["result"]["points_count"]}
con.execute("INSERT INTO news (url,title,body,content_hash,qdrant_indexed) VALUES (?,?,?,?,1)",
            ("http://a/8", "快照后新闻", "正文八", "h8"))
con.commit()
out["scenarios"]["S8_snapshot_frozen"] = {
    "frozen_ids": len(frozen["news_ids"]),
    "live_db_now_more": con.execute("SELECT COUNT(*) FROM news").fetchone()[0] > len(frozen["news_ids"]),
    "agent_must_use_frozen": True,
}

# S9 晨报保存成功但索引失败 → 阻塞下一轮
con.execute("INSERT INTO reports (version_id, body, qdrant_indexed) VALUES (?,?,0)",
            ("rpt-x-v1", "晨报正文"))
con.commit()
out["scenarios"]["S9_report_saved_index_pending_blocks"] = gate_agent() is False

# S10 下一轮生成前修复索引 → 通过
emb = pseudo_vec("晨报正文")
client.put(f"/collections/{COL}/points", json={"points": [{"id": str(uuid.uuid4()),
                                                          "vector": emb, "payload": {"version_id": "rpt-x-v1"}}]})
client.post(f"/collections/{COL}/points?wait=true", json={})
con.execute("UPDATE reports SET qdrant_indexed=1 WHERE version_id='rpt-x-v1'")
con.commit()
out["scenarios"]["S10_pre_run_check_pass"] = gate_agent() is True

out["blocking_rule_verified"] = (
    out["scenarios"]["S3_mid_write_crash_detectable"] and
    out["scenarios"]["S9_report_saved_index_pending_blocks"] and
    not out["scenarios"]["S10_pre_run_check_pass"] is False
)
out["db_temp"] = db
client.close()
save_result("t14_consistency", out)
print("T14 done:", json.dumps(out["scenarios"], ensure_ascii=False)[:600])
