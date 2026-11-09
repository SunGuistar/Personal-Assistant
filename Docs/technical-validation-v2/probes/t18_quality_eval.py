"""T18：独立质量评价验证（LIVE：DashScope qwen-flash，有限调用）。

- 只传入最终晨报正文（无原文/个人数据/中间结果）
- 五维评分（0-100）+ 综合分 + 自然语言评价，JSON 结构化输出
- 每份晨报评价 3 次 → 观察波动
- 评价失败路径（模型不存在）→ 报告保留
- 综合分公式对比：等权 vs 建议加权（资讯呈现/逻辑/AI分析/个人建议/阅读体验）
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE, load_hub_env, save_result, Timer

load_hub_env()
KEY = os.environ.get("DASHSCOPE_API_KEY", "")
FIX = json.loads((BASE / "fixtures" / "t18_sample_reports.json").read_text(encoding="utf-8"))
DIMS = ["资讯呈现", "内容逻辑与一致性", "AI技术分析", "个人总结与建议", "阅读体验"]

PROMPT = """你是晨报内容质量评价员。仅依据输入的晨报正文进行评价（不核验外部事实）。
按五个维度各打 0-100 分：资讯呈现、内容逻辑与一致性、AI技术分析、个人总结与建议、阅读体验。
另给出综合分（0-100）和一段 80 字以内的自然语言评价。
严格输出 JSON：{"dims": {"资讯呈现": n, ...}, "overall": n, "comment": "..."}"""

out = {"key_present": bool(KEY), "dims": DIMS, "samples": {}}

if KEY:
    H = {"Authorization": f"Bearer {KEY}"}

    def evaluate(body, model="qwen-flash"):
        with Timer() as t:
            r = httpx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                           headers=H, timeout=60, json={
                               "model": model,
                               "messages": [{"role": "system", "content": PROMPT},
                                            {"role": "user", "content": body}],
                               "response_format": {"type": "json_object"},
                               "temperature": 0.0, "max_tokens": 400})
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "error": str(r.json().get("error", {}))[:150]}
        try:
            return {"ok": True, "result": json.loads(r.json()["choices"][0]["message"]["content"]),
                    "elapsed_s": t.seconds,
                    "usage": r.json().get("usage")}
        except (json.JSONDecodeError, KeyError) as e:
            return {"ok": False, "parse_error": str(e), "raw": r.text[:200]}

    for rep in FIX["reports"]:
        runs = [evaluate(rep["body"]) for _ in range(3)]
        ok_runs = [r for r in runs if r.get("ok")]
        dims_matrix, overalls = [], []
        for r in ok_runs:
            dims_matrix.append([r["result"]["dims"].get(d) for d in DIMS])
            overalls.append(r["result"]["overall"])
        variance = (max(overalls) - min(overalls)) if len(overalls) > 1 else None
        out["samples"][rep["id"]] = {
            "label": rep["label"],
            "runs_ok": len(ok_runs),
            "overall_scores": overalls,
            "overall_range": variance,
            "dims_mean": ([round(sum(col) / len(col), 1) for col in zip(*dims_matrix)]
                          if dims_matrix else None),
            "comment_sample": ok_runs[0]["result"].get("comment", "")[:120] if ok_runs else None,
            "elapsed_mean_s": round(sum(r.get("elapsed_s", 0) for r in runs) / len(runs), 2),
            "usage_total_tokens": sum((r.get("usage") or {}).get("total_tokens", 0) for r in runs),
        }

    # 综合分公式对比（对每份样本的 3 次均值做计算演示）
    def calc(samples_scores, weights):
        return round(sum(s * w for s, w in zip(samples_scores, weights)), 1)

    means = {rid: s["dims_mean"] for rid, s in out["samples"].items() if s["dims_mean"]}
    formulas = {
        "等权平均": [0.2] * 5,
        "建议加权(资讯0.25/逻辑0.25/AI0.2/个人0.2/体验0.1)": [0.25, 0.25, 0.2, 0.2, 0.1],
        "重逻辑(0.15/0.35/0.2/0.2/0.1)": [0.15, 0.35, 0.2, 0.2, 0.1],
    }
    out["composite_formulas_demo"] = {
        name: {rid: calc(scores, w) for rid, scores in means.items()}
        for name, w in formulas.items()}

    # 失败路径：模型不存在 → 评价失败，报告保留
    bad = evaluate("测试正文", model="nonexistent-model-tv2")
    out["eval_failure_path"] = {
        "ok": not bad.get("ok"),
        "status": bad.get("status"),
        "report_preserved_logic": "评价失败 → eval_status='未评价/评价失败'，正文已保存不受影响",
    }

save_result("t18_quality_eval", out)
print("T18 done:", json.dumps({k: {kk: v[kk] for kk in ("runs_ok", "overall_scores")}
      for k, v in out["samples"].items()}, ensure_ascii=False))
