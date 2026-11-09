"""T20 补充：真实 Embedding（DashScope）事件语义归组（LIVE，有限调用）。

对 fixture 全量 16 篇正文各调用 1 次 text-embedding-v4（批量 1 次请求），
计算余弦相似度矩阵，与 TF-IDF 代理对照；记录真实 API 调用次数与耗时。
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE, load_hub_env, save_result

load_hub_env()
FIXTURE = json.loads((BASE / "fixtures" / "t20_dedup_samples.json").read_text(encoding="utf-8"))
SAMPLES = FIXTURE["samples"]
event_of = {s["id"]: s["event_id"] for s in SAMPLES}

import dashscope
from dashscope import TextEmbedding

key_present = bool(__import__("os").environ.get("DASHSCOPE_API_KEY", "").strip())
out = {"dashscope_key_present": key_present, "model": "text-embedding-v4"}

if key_present:
    t0 = time.perf_counter()
    texts = [s["title"] + "。" + s["body"] for s in SAMPLES]
    # text-embedding-v4 对 batch size 有约束（2 的幂且 <=10），按 4 一批调用
    embs = []
    api_calls = 0
    for i in range(0, len(texts), 4):
        resp0 = TextEmbedding.call(model="text-embedding-v4", input=texts[i:i + 4])
        api_calls += 1
        if resp0.status_code != 200:
            out.update({"ok": False, "status_code": resp0.status_code,
                        "error": str(resp0)[:300], "api_calls": api_calls})
            save_result("t20_embedding_semantics", out)
            print("T20 embedding probe failed:", resp0.status_code)
            raise SystemExit(0)
        embs += [r["embedding"] for r in resp0.output["embeddings"]]
    resp = resp0
    elapsed = time.perf_counter() - t0
    out["api_calls"] = api_calls
    if resp.status_code == 200:
        ids = [s["id"] for s in SAMPLES]

        def cos(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(x * x for x in b) ** 0.5
            return dot / (na * nb)

        pairs = []
        for i, j in itertools.combinations(range(len(ids)), 2):
            c = cos(embs[i], embs[j])
            if c >= 0.55:
                pairs.append({"pair": sorted([ids[i], ids[j]]),
                              "cos": round(c, 3),
                              "same_event": event_of[ids[i]] == event_of[ids[j]]})
        false_m = [p for p in pairs if not p["same_event"]]
        same_ev_pairs = [p for p in pairs if p["same_event"]]
        # 漏合并：同事件对的余弦最大值
        ev_best = {}
        for i, j in itertools.combinations(range(len(ids)), 2):
            if event_of[ids[i]] == event_of[ids[j]]:
                c = cos(embs[i], embs[j])
                ev = event_of[ids[i]]
                ev_best[ev] = max(ev_best.get(ev, 0), c)
        out.update({
            "ok": True, "api_calls": 1, "texts_embedded": len(texts),
            "elapsed_s": round(elapsed, 2),
            "pairs_above_0.55": pairs,
            "false_merge_pairs": false_m,
            "same_event_pairs_captured": len(same_ev_pairs),
            "best_cos_per_event": {k: round(v, 3) for k, v in ev_best.items()},
            "usage": resp.usage,
        })
    else:
        out.update({"ok": False, "status_code": resp.status_code,
                    "error": str(resp)[:200]})
else:
    out["ok"] = False
    out["note"] = "DASHSCOPE_API_KEY 未配置，Embedding 实测 BLOCKED"

save_result("t20_embedding_semantics", out)
print("T20 embedding probe done:", out.get("ok"))
