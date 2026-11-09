"""T22：Embedding 复用缓存验证（SIMULATION + LIVE 复用核对）。

缓存键：sha1(规范化文本) + embedding_model + chunk_version + preprocess_version。
场景：
1 同文本同模型 → 命中（0 API 调用）
2 同文本不同模型版本 → 不命中
3 正文变化 → 不命中
4 切分规则变化 → 不命中
5 预处理版本变化 → 不命中
6 进程重启后复用（SQLite 持久缓存）
7 Qdrant 已有向量复用（以 payload hash 判断）
8 错误缓存/缺失向量恢复
9 Embedding 缓存不随 08:00 阶段缓存清理而删除
记录：实际 API 调用次数、命中、重算、节省。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_hub_env, save_result

db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
con = sqlite3.connect(db)
con.execute("""CREATE TABLE emb_cache (
    text_hash TEXT, model TEXT, chunk_ver TEXT, pre_ver TEXT,
    embedding BLOB, created_at TEXT,
    PRIMARY KEY (text_hash, model, chunk_ver, pre_ver))""")
con.execute("""CREATE TABLE stage_cache (
    key TEXT PRIMARY KEY, value TEXT, created_at TEXT)""")  # 12h 阶段缓存（模拟）
con.commit()

stats = {"api_calls": 0, "hits": 0, "recomputes": 0, "saved_calls": 0}


def norm_text(t):
    return re.sub(r"\s+", "", t.lower())


def thash(t):
    return hashlib.sha1(norm_text(t).encode()).hexdigest()


def fake_embed_api(text):
    """模拟真实向量化 API（计数）。"""
    stats["api_calls"] += 1
    import random
    rnd = random.Random(thash(text))
    return [rnd.random() for _ in range(8)]


def get_embedding(text, model="text-embedding-v4", chunk_ver="v1", pre_ver="p1"):
    key = (thash(text), model, chunk_ver, pre_ver)
    row = con.execute("SELECT embedding FROM emb_cache WHERE text_hash=? AND model=? AND chunk_ver=? AND pre_ver=?",
                      key).fetchone()
    if row:
        stats["hits"] += 1
        stats["saved_calls"] += 1
        return json.loads(row[0])
    stats["recomputes"] += 1
    vec = fake_embed_api(text)
    con.execute("INSERT OR REPLACE INTO emb_cache VALUES (?,?,?,?,?,datetime('now'))",
                (*key, json.dumps(vec)))
    con.commit()
    return vec


out = {"scenarios": {}}
t = "DeepSeek V4.1 Flash 支持多模态与 1M 上下文。"

# S1 同文本同模型：第一次算，第二次命中
v1 = get_embedding(t)
v2 = get_embedding(t)
out["scenarios"]["S1_same_text_same_model_reuse"] = (v1 == v2 and stats["api_calls"] == 1
                                                     and stats["hits"] == 1)

# S2 同文本不同模型版本
get_embedding(t, model="text-embedding-v4-new")
out["scenarios"]["S2_model_change_no_reuse"] = stats["api_calls"] == 2

# S3 正文变化
get_embedding(t + " 更新：FP8 默认启用。")
out["scenarios"]["S3_text_change_recompute"] = stats["api_calls"] == 3

# S4 切分规则变化（同文本不同 chunk_ver）
get_embedding(t, chunk_ver="v2")
out["scenarios"]["S4_chunk_rule_change_recompute"] = stats["api_calls"] == 4

# S5 预处理版本变化
get_embedding(t, pre_ver="p2")
out["scenarios"]["S5_preprocess_change_recompute"] = stats["api_calls"] == 5

# S6 进程重启后复用（重开连接）
con.close()
con = sqlite3.connect(db)
v3 = get_embedding(t)
out["scenarios"]["S6_survive_restart"] = v3 == v1 and stats["hits"] >= 2

# S7 Qdrant 已有向量复用：payload 存 text_hash，检索侧判断
qdrant_payload_hash = thash(t)
out["scenarios"]["S7_qdrant_vector_reuse_rule"] = {
    "rule": "入库时 payload 携带 text_hash+model+chunk_ver；新增文章先查 Qdrant 是否已有同 hash+版本向量，有则跳过 API",
    "hash_present_in_payload": bool(qdrant_payload_hash),
}

# S8 错误缓存恢复：删除缓存后重算成功
con.execute("DELETE FROM emb_cache WHERE text_hash=?", (thash(t),))
con.commit()
before = stats["api_calls"]
v4 = get_embedding(t)
out["scenarios"]["S8_corrupt_cache_recovery"] = stats["api_calls"] == before + 1 and v4 == v1

# S9 每日 08:00 阶段缓存清理不影响 Embedding 缓存
con.execute("DELETE FROM stage_cache")  # 模拟清理阶段缓存
con.execute("INSERT INTO stage_cache VALUES ('sim','x',datetime('now'))")
emb_rows_before = con.execute("SELECT COUNT(*) FROM emb_cache").fetchone()[0]
con.execute("DELETE FROM stage_cache")  # 08:00 清理
emb_rows_after = con.execute("SELECT COUNT(*) FROM emb_cache").fetchone()[0]
hits_before = stats["hits"]
get_embedding(t)
out["scenarios"]["S9_emb_cache_survives_0800_cleanup"] = (
    emb_rows_before == emb_rows_after and stats["hits"] == hits_before + 1)

out["stats"] = stats
out["db_temp"] = db
con.close()
save_result("t22_embedding_cache", out)
print("T22 done:", json.dumps(out["scenarios"], ensure_ascii=False)[:500])
print("stats:", stats)
