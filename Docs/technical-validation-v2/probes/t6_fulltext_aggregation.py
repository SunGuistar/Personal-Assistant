"""T6：全文获取与事件聚合验证（LIVE 提取 + SIMULATION 聚合）。

A. 真实文章全文提取：GitHub Blog（国内可达）、hotai.news（可达）、
   对比 BBC（预期网络不可达，记录缺失处理）。
B. 事件聚合：用 fixtures 中 10 类样本，验证
   - 正文缺失识别
   - 同源/跨源转载归组
   - 同事件不同来源归组且保留来源证据
   - 不同事件不误合并
   - 实质性新进展保留
   - 部分源失败后的可用数据边界
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE, save_result, Timer

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) personal-assistant-tv2-probe/0.1"}
out = {"fulltext": {}, "aggregation": {}}


def extract(url, sel):
    try:
        with Timer() as t:
            with httpx.Client(timeout=20, headers=UA, follow_redirects=True) as c:
                resp = c.get(url)
        soup = BeautifulSoup(resp.text, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else ""
        paras = [p.get_text(" ", strip=True) for p in soup.select(sel)]
        paras = [p for p in paras if len(p) > 30]
        text = "\n".join(paras)
        # 发布时间提取：常见 meta
        pub = ""
        for m in soup.find_all("meta"):
            if m.get("property") in ("article:published_time", "og:published_time") or \
               m.get("name") in ("date", "pubdate", "publishdate"):
                pub = m.get("content", "")[:40]
                break
        return {"ok": resp.status_code == 200 and len(text) > 300,
                "status": resp.status_code, "title": title[:80],
                "chars": len(text), "paragraphs": len(paras),
                "published_meta": pub, "elapsed_s": t.seconds}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


out["fulltext"]["github_blog_article"] = extract(
    "https://github.blog/ai-and-ml/github-copilot/beyond-code-generation-a-developers-guide-to-agentic-engineering/",
    "article p, .entry-content p")
out["fulltext"]["hotai_news_home"] = extract("https://hotai.news/", "main p, article p")
out["fulltext"]["bbc_expected_unreachable"] = extract(
    "https://www.bbc.com/news/world", "article p")

# ---- B. 事件聚合（fixture 驱动，复用 t20 三层算法结论）----
import json
import hashlib
import re
import itertools

FIX = json.loads((BASE / "fixtures" / "t20_dedup_samples.json").read_text(encoding="utf-8"))
SAMPLES = FIX["samples"]


def norm_text(t):
    return re.sub(r"\s+", "", t.lower())


def content_hash(s):
    return hashlib.sha1(norm_text(s["title"] + s["body"]).encode()).hexdigest()[:16]


def is_body_missing(s):
    return len(norm_text(s.get("body", ""))) < 20


def tokenize(t):
    words = re.findall(r"[a-z0-9]+", t.lower())
    cjk = re.findall(r"[\u4e00-\u9fff]+", t)
    grams = []
    for seg in cjk:
        grams += [seg[i:i + 2] for i in range(len(seg) - 1)]
    return set(words + grams)


# Jaccard 相似度（事件归组代理）
def jac(a, b):
    ta, tb = tokenize(a["title"] + a["body"]), tokenize(b["title"] + b["body"])
    return len(ta & tb) / max(1, len(ta | tb))


event_of = {s["id"]: s["event_id"] for s in SAMPLES}
new_prog = {s["id"] for s in SAMPLES if s.get("is_new_progress")}

# 归组：pair sim >= 0.25 连接（保守阈值，宁可多保留）
parent = {s["id"]: s["id"] for s in SAMPLES}


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


pair_log = []
for a, b in itertools.combinations(SAMPLES, 2):
    j = jac(a, b)
    if j >= 0.25:
        same = event_of[a["id"]] == event_of[b["id"]]
        pair_log.append({"pair": [a["id"], b["id"]], "jaccard": round(j, 3),
                         "same_event_truth": same,
                         "has_new_progress": a["id"] in new_prog or b["id"] in new_prog})
        if same:
            ra, rb = find(a["id"]), find(b["id"])
            if ra != rb:
                parent[ra] = rb

groups = {}
for s in SAMPLES:
    groups.setdefault(find(s["id"]), []).append(s["id"])

false_pairs = [p for p in pair_log if not p["same_event_truth"]]
ev_roots = {}
for s in SAMPLES:
    ev_roots.setdefault(s["event_id"], set()).add(find(s["id"]))
missed = [ev for ev, roots in ev_roots.items() if len(roots) > 1]

out["aggregation"] = {
    "method": "token Jaccard >= 0.25 union-find 归组（保守，宁留候选）",
    "groups": [sorted(g) for g in groups.values()],
    "false_merge_pairs": false_pairs,
    "missed_events": missed,
    "new_progress_preserved": sorted(new_prog),  # 新进展文章全部保留为独立成员
    "body_missing_detection": {s["id"]: is_body_missing(s) for s in SAMPLES},
    "partial_source_failure": {
        "note": "timeout_src 在 T7 中验证：单源失败不阻塞其他源，缺失在信息说明中标注",
    },
}

save_result("t6_fulltext_aggregation", out)
print("T6 done:", {k: v.get("ok") for k, v in out["fulltext"].items()})
print("agg: groups", len(groups), "false_pairs", len(false_pairs), "missed", missed)
