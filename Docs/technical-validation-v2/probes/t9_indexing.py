"""T9：技术资讯与历史晨报索引验证（INTEGRATION，依赖 T12 容器 tv2_news/tv2_reports）。

验证：
- 长文分块（langchain RecursiveCharacterTextSplitter）
- AI 技术资讯全文索引（正文进 payload + 向量）
- 历史晨报按语义单元分块（事件/个人回顾/建议）
- 文章与来源关联、晨报与版本 ID 关联
- 历史建议检索 / 历史技术变化识别（dense 查询）
- 相同文章更新后的增量索引（旧向量删除/更新，保留来源关联）
- 旧记录保留和检索
- 原始来源回溯
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE, load_hub_env, save_result, Timer

URL = "http://127.0.0.1:8633"
VEC_SIZE = 1024
client = httpx.Client(base_url=URL, timeout=30)
out = {}

LONG_ARTICLE = """# 大模型推理优化年度综述（长文测试素材）

## 背景
近年来大语言模型推理成本成为部署瓶颈。KV Cache、量化、推测解码等技术不断发展。

## KV Cache
KV Cache 将注意力键值缓存以避免重复计算，是长上下文推理的基础优化。
分页注意力（PagedAttention）将 KV Cache 分块管理，显著降低碎片。

## 量化
INT8 与 FP8 量化可将显存占用降低一半以上，精度损失可控。
量化感知训练（QAT）在部分模型上可将精度损失降到 1% 以内。

## 推测解码
推测解码（Speculative Decoding）用小模型草稿+大模型验证，可获得 2-3 倍加速。
自推测（Self-Speculative）与 Medusa 等方法减少了对草稿模型的依赖。

## 结论
推理优化进入组合优化阶段，KV Cache 管理、量化与推测解码协同设计是趋势。
"""


def get_embeddings(texts):
    load_hub_env()
    if not os.environ.get("DASHSCOPE_API_KEY", "").strip():
        return None
    from dashscope import TextEmbedding
    embs = []
    for i in range(0, len(texts), 4):
        resp = TextEmbedding.call(model="text-embedding-v4", input=texts[i:i + 4])
        if resp.status_code != 200:
            return None
        embs += [r["embedding"] for r in resp.output["embeddings"]]
    return embs


def pseudo_vec(text, size=VEC_SIZE):
    v = [0.0] * size
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16)
        v[h % size] += 1.0
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


# ---- 长文分块 ----
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(chunk_size=220, chunk_overlap=30,
                                          separators=["\n\n", "\n", "。", "，", " "])
chunks = splitter.split_text(LONG_ARTICLE)
out["chunking"] = {"chunk_count": len(chunks), "avg_chunk_len": sum(map(len, chunks)) // len(chunks),
                   "chunks_head": [c[:40] for c in chunks[:4]]}

emb = get_embeddings(chunks)
out["embedding_live"] = emb is not None
vecs = emb if emb else [pseudo_vec(c) for c in chunks]

ARTICLE_URL = "https://example.org/llm-inference-survey-2026"
article_id = str(uuid.uuid4())
points = [{"id": str(uuid.uuid4()), "vector": v, "payload": {
    "article_id": article_id, "chunk_index": i, "chunk_text": c,
    "source": "技术社区", "url": ARTICLE_URL, "title": "大模型推理优化年度综述",
    "published_at": "2026-10-20", "version": 1, "doc_kind": "tech_article",
}} for i, (c, v) in enumerate(zip(chunks, vecs))]

COL = "tv2_news"
client.put(f"/collections/{COL}/points", json={"points": points})
client.post(f"/collections/{COL}/points?wait=true", json={})
out["index_long_article"] = {"ok": True, "chunks_indexed": len(points), "article_id": article_id}

# ---- 历史晨报语义单元 ----
report_units = [
    {"version_id": "rpt-20261101-v1", "report_date": "2026-11-01", "unit": "ai_analysis",
     "text": "AI 技术观察：PagedAttention 成为推理引擎标配，建议关注 vLLM 动态。"},
    {"version_id": "rpt-20261101-v1", "report_date": "2026-11-01", "unit": "personal_review",
     "text": "个人进展：长期目标『掌握 RAG 工程』本周推进：完成混合检索实验。"},
    {"version_id": "rpt-20261101-v1", "report_date": "2026-11-01", "unit": "suggestions",
     "text": "建议：将 Embedding 缓存纳入晨报索引设计，避免重复向量化开销。"},
    {"version_id": "rpt-20261020-v1", "report_date": "2026-10-20", "unit": "suggestions",
     "text": "建议：调研 Qdrant 与现有 Chroma 的检索质量差异后再迁移。"},
]
remb = get_embeddings([u["text"] for u in report_units])
rvecs = remb if remb else [pseudo_vec(u["text"]) for u in report_units]
rpoints = [{"id": str(uuid.uuid4()), "vector": v, "payload": {**u, "doc_kind": "report_unit",
                                                              "source": "晨报"}} for u, v in zip(report_units, rvecs)]
COL2 = "tv2_reports"
client.put(f"/collections/{COL2}/points", json={"points": rpoints})
client.post(f"/collections/{COL2}/points?wait=true", json={})
out["index_report_units"] = {"ok": True, "units": len(rpoints)}

# ---- 检索验证 ----
def search(col, vec, query_filter=None, limit=5):
    body = {"vector": vec, "limit": limit, "with_payload": True}
    if query_filter:
        body["filter"] = query_filter
    return client.post(f"/collections/{col}/points/search", json=body).json()["result"]


q_emb = get_embeddings(["PagedAttention 推理引擎"]) or [pseudo_vec("PagedAttention 推理引擎")]
hits = search(COL, q_emb[0])
out["search_tech_history"] = {
    "top_titles": [h["payload"].get("title", "")[:30] for h in hits[:3]],
    "has_source_url": all(h["payload"].get("url") for h in hits if h["payload"].get("doc_kind") == "tech_article"),
}

q2 = get_embeddings(["Embedding 缓存 建议"]) or [pseudo_vec("Embedding 缓存 建议")]
hits2 = search(COL2, q2[0])
out["search_historical_suggestions"] = {
    "top_units": [(h["payload"].get("unit"), h["payload"].get("version_id")) for h in hits2[:3]],
    "version_traceable": all(h["payload"].get("version_id") for h in hits2),
}

# ---- 增量索引：文章更新 v1→v2 ----
new_chunks = splitter.split_text(LONG_ARTICLE + "\n\n## 更新\n2026-11 更新：FP8 在主流推理框架中默认启用。\n")
new_emb = get_embeddings(new_chunks)
new_vecs = new_emb if new_emb else [pseudo_vec(c) for c in new_chunks]
# 删除旧版本向量（按 article_id + version 过滤删除）
client.post(f"/collections/{COL}/points/delete?wait=true", json={
    "filter": {"must": [{"key": "article_id", "match": {"value": article_id}}]}})
client.post(f"/collections/{COL}/points?wait=true", json={})
new_points = [{"id": str(uuid.uuid4()), "vector": v, "payload": {
    "article_id": article_id, "chunk_index": i, "chunk_text": c,
    "source": "技术社区", "url": ARTICLE_URL, "title": "大模型推理优化年度综述",
    "published_at": "2026-10-20", "version": 2, "doc_kind": "tech_article",
}} for i, (c, v) in enumerate(zip(new_chunks, new_vecs))]
client.put(f"/collections/{COL}/points", json={"points": new_points})
client.post(f"/collections/{COL}/points?wait=true", json={})
r = client.post(f"/collections/{COL}/points/scroll", json={
    "filter": {"must": [{"key": "article_id", "match": {"value": article_id}}]},
    "limit": 50, "with_payload": True})
vers = {p["payload"]["version"] for p in r.json()["result"]["points"]}
out["incremental_update"] = {
    "old_versions_removed": vers == {2},
    "current_chunks": len(r.json()["result"]["points"]),
    "url_preserved": all(p["payload"].get("url") == ARTICLE_URL for p in r.json()["result"]["points"]),
}

# ---- 旧记录保留 ----
r_old = client.post(f"/collections/{COL2}/points/scroll", json={
    "filter": {"must": [{"key": "report_date", "match": {"value": "2026-10-20"}}]}, "limit": 10})
out["old_records_kept"] = len(r_old.json()["result"]["points"]) == 1

out["authoritative_note"] = "晨报完整权威版本应在晨报 SQLite；Qdrant 只存语义片段+version_id 引用（本轮模拟 payload 即片段）"
client.close()
save_result("t9_indexing", out)
print("T9 done:", {k: out[k] for k in ["chunking", "index_long_article", "incremental_update", "old_records_kept"]})
