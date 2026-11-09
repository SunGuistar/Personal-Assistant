"""T21：Query 改写与 Rerank 四模式对比（INTEGRATION + LIVE 可选）。

模式：A 基线（关闭/关闭） B 改写  C Rerank  D 改写+Rerank
召回：Qdrant dense（tv2_rag_news / tv2_rag_reports）+ 客户端 BM25，RRF 融合。
改写：DashScope qwen-plus（LIVE，每查询 1 次）+ 启发式降级。
Rerank：DashScope gte-rerank（若可用，LIVE），否则 BM25 重排代理（标注）。
指标：Recall@5、MRR@5、延迟、额外调用次数。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE, load_hub_env, save_result

URL = "http://127.0.0.1:8633"
VEC_SIZE = 1024
FIX = json.loads((BASE / "fixtures" / "t21_rag_queries.json").read_text(encoding="utf-8"))
CORPUS, QUERIES = FIX["corpus"], FIX["queries"]
client = httpx.Client(base_url=URL, timeout=30)
out = {"modes": {}, "per_query": []}

load_hub_env()
HAS_DASH = bool(os.environ.get("DASHSCOPE_API_KEY", ""))


def get_embeddings(texts):
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


# 建库
cols = {"news": "tv2_rag_news", "reports": "tv2_rag_reports"}
for c in cols.values():
    client.put(f"/collections/{c}", json={"vectors": {"size": VEC_SIZE, "distance": "Cosine"}})
texts = [d["title"] + "。" + d["text"] for d in CORPUS]
embs = get_embeddings(texts) if HAS_DASH else None
out["embedding_live"] = embs is not None
vecs = embs if embs else [pseudo_vec(t) for t in texts]
by_col = {}
for d, v in zip(CORPUS, vecs):
    payload = {k: d[k] for k in d if k not in ("col", "title", "text")}
    payload["title"] = d["title"]
    payload["full_text"] = d["text"]
    by_col.setdefault(cols[d["col"]], []).append(
        {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "tv2-rag/" + d["id"])), "vector": v, "payload": payload})
for c, pts in by_col.items():
    client.put(f"/collections/{c}/points", json={"points": pts})
    client.post(f"/collections/{c}/points?wait=true", json={})


def dense_search(qvec, limit=10):
    res = []
    for c in cols.values():
        r = client.post(f"/collections/{c}/points/search", json={
            "vector": qvec, "limit": limit, "with_payload": True}).json()["result"]
        res += [{"id": p["id"], "score": p["score"], "payload": p["payload"]} for p in r]
    return res


def bm25_all(query, limit=10):
    from rank_bm25 import BM25Okapi
    res = []
    for c in cols.values():
        pts = client.post(f"/collections/{c}/points/scroll", json={
            "limit": 100, "with_payload": True}).json()["result"]["points"]
        corpus = [(p["payload"].get("title", "") + " " +
                   p["payload"].get("full_text", "")).lower().split() for p in pts]
        if not corpus:
            continue
        bm = BM25Okapi(corpus)
        scores = bm.get_scores(query.lower().split())
        ranked = sorted(zip(pts, scores), key=lambda x: -x[1])[:limit]
        res += [{"id": p["id"], "score": s, "payload": p["payload"]} for p, s in ranked if s > 0]
    return res


def rrf(dense, bm, k=60, limit=10):
    acc = {}
    for rank, p in enumerate(dense):
        acc[p["id"]] = acc.get(p["id"], 0) + 1 / (k + rank + 1)
        acc[(p["id"], "p")] = p["payload"]
    for rank, p in enumerate(bm):
        acc[p["id"]] = acc.get(p["id"], 0) + 1 / (k + rank + 1)
        acc[(p["id"], "p")] = p["payload"]
    ranked = sorted([(i, s) for i, s in acc.items() if isinstance(i, str)],
                    key=lambda x: -x[1])[:limit]
    return [{"id": i, "payload": acc[(i, "p")]} for i, _ in ranked]


def llm_rewrite(q):
    """DashScope qwen-flash 改写（LIVE，兼容端点）；失败返回 None 走降级。"""
    if not HAS_DASH:
        return None
    try:
        import httpx as _httpx
        r = _httpx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                        headers={"Authorization": f"Bearer {os.environ['DASHSCOPE_API_KEY']}"},
                        timeout=30, json={
                            "model": "qwen-flash",
                            "messages": [
                                {"role": "system", "content": "你是检索查询改写助手。把用户问题改写为更适合检索的查询，补充同义词、英文术语和别名，不得编造事实，保持原意，输出一行查询即可。"},
                                {"role": "user", "content": q}],
                            "temperature": 0.0, "max_tokens": 60})
        j = r.json()
        if r.status_code == 200 and j.get("choices"):
            return j["choices"][0]["message"]["content"].strip().split("\n")[0][:100]
    except Exception:
        return None
    return None


def heuristic_rewrite(q):
    # 极简降级：同义词扩展表
    syn = {"deepseek": ["deepseek", "deep seek"], "缓存": ["缓存", "cache"],
           "模型": ["模型", "model"], "检索": ["检索", "retrieval", "search"]}
    extra = []
    for k, vs in syn.items():
        if k in q:
            extra += vs
    return q + " " + " ".join(dict.fromkeys(extra))


RERANK_LIVE = False


def rerank(query, candidates, top_n=5):
    """优先 DashScope gte-rerank（LIVE）；失败用 BM25 代理重排。"""
    global RERANK_LIVE
    if HAS_DASH and not RERANK_LIVE:
        try:
            import dashscope
            docs = [c["payload"].get("title", "") + " " + c["payload"].get("full_text", "")[:200]
                    for c in candidates]
            resp = dashscope.TextReRank.call(model="gte-rerank", query=query, documents=docs,
                                             top_n=top_n, return_documents=False)
            if resp.status_code == 200:
                RERANK_LIVE = True
                order = [r["index"] for r in resp.output["results"]]
                return [candidates[i] for i in order]
        except Exception:
            pass
    # 代理：BM25 按 query 对候选重排
    from rank_bm25 import BM25Okapi
    corpus = [(c["payload"].get("title", "") + " " + c["payload"].get("full_text", "")).lower().split()
              for c in candidates]
    if not corpus:
        return candidates[:top_n]
    bm = BM25Okapi(corpus)
    scores = bm.get_scores(query.lower().split())
    order = sorted(range(len(candidates)), key=lambda i: -scores[i])
    return [candidates[i] for i in order[:top_n]]


def metrics(ranked_ids, relevant):
    k = 5
    topk = ranked_ids[:k]
    recall = len(set(topk) & set(relevant)) / len(relevant)
    rr = 0.0
    for i, d in enumerate(ranked_ids[:10]):
        if d in relevant:
            rr = 1.0 / (i + 1)
            break
    return recall, rr


MODE_NAMES = {"A": "基线", "B": "改写", "C": "Rerank", "D": "改写+Rerank"}
agg = {m: {"recall": [], "mrr": [], "ms": [], "extra_calls": 0} for m in MODE_NAMES}
rewrite_deviation = []
rerank_source_check = []

for q in QUERIES:
    row = {"q": q["q"], "category": q["category"], "relevant": q["relevant"]}
    for mode in MODE_NAMES:
        t0 = time.perf_counter()
        use_rewrite = mode in ("B", "D")
        use_rerank = mode in ("C", "D")
        query_text = q["q"]
        extra = 0
        if use_rewrite:
            rw = llm_rewrite(q["q"])
            if rw is None:
                rw = heuristic_rewrite(q["q"])
            else:
                extra += 1
            if rw != q["q"]:
                rewrite_deviation.append({"q": q["q"], "rewritten": rw})
            query_text = rw
        qvec = (get_embeddings([query_text]) or [pseudo_vec(query_text)])[0]
        base = rrf(dense_search(qvec), bm25_all(query_text))
        if use_rerank:
            base = rerank(query_text, base, top_n=5)
            extra += 1
        ids = [b["payload"].get("id", b["id"]) for b in base]
        rec, rr = metrics(ids, q["relevant"])
        agg[mode]["recall"].append(rec)
        agg[mode]["mrr"].append(rr)
        agg[mode]["ms"].append((time.perf_counter() - t0) * 1000)
        agg[mode]["extra_calls"] += extra
        row[f"mode_{mode}"] = {"recall@5": rec, "mrr": round(rr, 3),
                               "top_id": ids[0] if ids else None}
        if mode == "D":
            ok_sources = all(b["payload"].get("source") for b in base)
            rerank_source_check.append(ok_sources)
    out["per_query"].append(row)

for m in MODE_NAMES:
    a = agg[m]
    out["modes"][m] = {
        "name": MODE_NAMES[m],
        "recall@5_mean": round(sum(a["recall"]) / len(a["recall"]), 3),
        "mrr_mean": round(sum(a["mrr"]) / len(a["mrr"]), 3),
        "latency_mean_ms": round(sum(a["ms"]) / len(a["ms"]), 1),
        "extra_llm_calls_total": a["extra_calls"],
    }
out["rewrite_live_llm"] = HAS_DASH
out["rerank_live"] = RERANK_LIVE
out["rewrite_samples"] = rewrite_deviation[:6]
out["rerank_sources_kept"] = all(rerank_source_check)
out["label_caveat"] = ("查询样本 n=8，标注者为本轮验证者一人，指标仅作方案间相对比较，"
                       "不构成统计显著结论")
client.close()
save_result("t21_rag_modes", out)
print("T21 done:", json.dumps(out["modes"], ensure_ascii=False))
print("rerank live:", RERANK_LIVE)
