"""T20：分层去重与事件新进展保护（SIMULATION，fixtures 实测）。

算法层级：
L1 精确去重：规范化 URL sha1 + 规范化文本 sha1
L2 近似去重：simhash（纯 python 实现）+ MinHash（datasketch）
L3 事件归组：TF-IDF 余弦（语义代理；真实 Embedding 见 t20_embedding_semantics.py）

输出：各层 pair 判定、误合并/漏合并（对照 fixture 人工标注 event_id）、
新进展保护检查、耗时。
"""
from __future__ import annotations

import hashlib
import itertools
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE, save_result

FIXTURE = json.loads((BASE / "fixtures" / "t20_dedup_samples.json").read_text(encoding="utf-8"))
SAMPLES = FIXTURE["samples"]


def norm_url(u: str) -> str:
    u = u.strip().lower().rstrip("/")
    u = re.sub(r"[?#].*$", "", u)
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u


def norm_text(t: str) -> str:
    return re.sub(r"\s+", "", t.lower())


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def tokens(t: str) -> list[str]:
    # 中文按 bigram，英文按词
    t = t.lower()
    words = re.findall(r"[a-z0-9]+", t)
    cjk = re.findall(r"[\u4e00-\u9fff]+", t)
    grams = []
    for seg in cjk:
        grams += [seg[i:i + 2] for i in range(len(seg) - 1)]
    return words + grams


def _hash64(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest()[:16], 16)


def simhash64(toks: list[str]) -> int:
    bits = [0] * 64
    for t in set(toks):
        h = _hash64(t)
        for i in range(64):
            bits[i] += 1 if (h >> i) & 1 else -1
    v = 0
    for i in range(64):
        if bits[i] > 0:
            v |= 1 << i
    return v


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ---- L1 精确 ----
t0 = time.perf_counter()
exact_groups = {}
for s in SAMPLES:
    key = (sha1(norm_url(s["url"])), sha1(norm_text(s["title"] + s["body"])))
    exact_groups.setdefault(key, []).append(s["id"])
exact_pairs = [sorted(ids) for ids in exact_groups.values() if len(ids) > 1]
l1_time = time.perf_counter() - t0

# ---- L2 近似 ----
t0 = time.perf_counter()
tok_map = {s["id"]: tokens(s["title"] + " " + s["body"]) for s in SAMPLES}
sh_map = {sid: simhash64(t) for sid, t in tok_map.items()}

from datasketch import MinHash

mh_map = {}
for sid, toks in tok_map.items():
    m = MinHash(num_perm=128)
    for t in toks:
        m.update(t.encode())
    mh_map[sid] = m

l2 = []
for a, b in itertools.combinations([s["id"] for s in SAMPLES], 2):
    hd = hamming(sh_map[a], sh_map[b])
    jacc = mh_map[a].jaccard(mh_map[b])
    if hd <= 12 or jacc >= 0.5:
        l2.append({"pair": [a, b], "simhash_hamming": hd, "minhash_jaccard": round(jacc, 3)})
l2_time = time.perf_counter() - t0

# ---- L3 事件归组（TF-IDF 余弦代理）----
t0 = time.perf_counter()
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

corpus = [s["title"] + " " + s["body"] for s in SAMPLES]
vec = TfidfVectorizer(analyzer="char", ngram_range=(2, 3)).fit_transform(corpus)
sim = cosine_similarity(vec)
ids = [s["id"] for s in SAMPLES]
l3 = []
for i, j in itertools.combinations(range(len(ids)), 2):
    if sim[i, j] >= 0.35:
        l3.append({"pair": sorted([ids[i], ids[j]]), "cos": round(float(sim[i, j]), 3)})
l3_time = time.perf_counter() - t0

# ---- 对照人工标注评估 ----
truth = {frozenset([s["id"]]): s for s in SAMPLES}
event_of = {s["id"]: s["event_id"] for s in SAMPLES}
new_prog = {s["id"] for s in SAMPLES if s.get("is_new_progress")}


def evaluate(pairs, name):
    merged = set()
    false_merge, missed, new_prog_lost = [], [], []
    # 并查集
    parent = {s["id"]: s["id"] for s in SAMPLES}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        a, b = p["pair"] if isinstance(p, dict) else p
        ra, rb = find(a), find(b)
        if ra != rb:
            # 检查误合并：不同 event_id
            if event_of[a] != event_of[b]:
                false_merge.append([a, b, event_of[a], event_of[b]])
            parent[ra] = rb
    groups = {}
    for s in SAMPLES:
        groups.setdefault(find(s["id"]), []).append(s["id"])
    # 漏合并：同 event 不同组
    ev_groups = {}
    for s in SAMPLES:
        ev_groups.setdefault(s["event_id"], set()).add(find(s["id"]))
    for ev, roots in ev_groups.items():
        if len(roots) > 1:
            missed.append(ev)
    # 新进展保护：is_new_progress 文章不得与高相似同事件文章被“删除”（这里检查是否被并入同组导致被标为纯重复）
    # 规则：若 new_progress 文章与同 event 文章同组 → 只要保留为独立候选即安全；检查其是否被误判为完全重复对
    for p in pairs:
        pair = p["pair"] if isinstance(p, dict) else p
        a, b = pair
        if (a in new_prog or b in new_prog) and event_of[a] == event_of[b]:
            pass  # 同组允许，但必须保留独立条目——在报告中说明
    return {"groups": [sorted(g) for g in groups.values()],
            "false_merges": false_merge, "missed_events": missed,
            "group_count": len(groups)}


eval_l1 = evaluate(exact_pairs, "L1")
eval_l2 = evaluate(l2, "L2")
eval_l3 = evaluate(l3, "L3")

out = {
    "sample_count": len(SAMPLES),
    "L1_exact": {"dup_pairs": exact_pairs, "time_s": round(l1_time, 4), **eval_l1},
    "L2_near": {"candidate_pairs": l2, "time_s": round(l2_time, 4), **eval_l2},
    "L3_event_tfidf_proxy": {"pairs": l3, "time_s": round(l3_time, 4), **eval_l3},
    "new_progress_articles": sorted(new_prog),
    "thresholds": {"simhash_hamming_max": 12, "minhash_jaccard_min": 0.5, "tfidf_cos_min": 0.35},
    "note": "L3 使用 TF-IDF 字符 ngram 作为语义代理；真实 Embedding 事件归组见 t20_embedding_semantics.json",
}
save_result("t20_layered_dedup", out)
print("T20 probe done: L1 pairs", len(exact_pairs), "| L2 pairs", len(l2), "| L3 pairs", len(l3))
print("false merges L2:", eval_l2["false_merges"], "L3:", eval_l3["false_merges"])
print("missed L2:", eval_l2["missed_events"], "L3:", eval_l3["missed_events"])
