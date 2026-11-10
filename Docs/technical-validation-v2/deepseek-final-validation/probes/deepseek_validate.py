# -*- coding: utf-8 -*-
"""DeepSeek API 真实调用专项验证（T8 补测）。

真实计费调用 ≤4 次（中文生成 / JSON 输出 / Tool Calling / Streaming），
另有 /models 列表查询（不计费）与两项异常模拟（伪造 Key 401、极小超时，均不计费）。
结果（不含任何密钥）存 results/deepseek_validation.json。

运行（仓库根目录）：
  python Docs/technical-validation-v2/deepseek-final-validation/probes/deepseek_validate.py
"""
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[4]
BASE_URL = "https://api.deepseek.com"
OUT = Path(__file__).resolve().parent.parent / "results" / "deepseek_validation.json"
CST = timezone(timedelta(hours=8))

# UTC 高峰：周一至周五（不含中国法定节假日）01:00-04:00、06:00-10:00 UTC
PEAK_WINDOWS_UTC = [(1, 4), (6, 10)]


def load_key():
    """经项目 env_bootstrap 加载，只返回存在性，绝不输出密钥。"""
    sys.path.insert(0, str(REPO))
    import env_bootstrap
    env_bootstrap.load_hub_env()
    import os
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    assert key, "DEEPSEEK_API_KEY 未加载"
    return key


def is_peak_now(now_cst):
    now_utc = now_cst.astimezone(timezone.utc)
    if now_cst.weekday() >= 5:  # 周末全天低谷
        return False, "weekend"
    for start, end in PEAK_WINDOWS_UTC:
        if start <= now_utc.hour < end:
            return True, f"peak UTC {start:02d}:00-{end:02d}:00"
    return False, "off-peak weekday"


def chat(key, payload, timeout=60, tag=""):
    t0 = time.perf_counter()
    r = requests.post(f"{BASE_URL}/chat/completions", json=payload,
                      headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
    elapsed = round(time.perf_counter() - t0, 3)
    body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else r.text
    return {"tag": tag, "http": r.status_code, "elapsed_s": elapsed, "body": body}


def mask_usage(u):
    """usage 全字段保留（无敏感信息）。"""
    return u


def main():
    now_cst = datetime.now(CST)
    peak, reason = is_peak_now(now_cst)
    result = {
        "validated_at_cst": now_cst.isoformat(),
        "peak_check": {"is_peak": peak, "reason": reason,
                       "rule": "Mon-Fri excl. CN holidays, UTC 01:00-04:00 & 06:00-10:00 = peak; else off-peak (half price)"},
        "pricing_reference": {
            "source": "https://api-docs.deepseek.com/quick_start/pricing (fetched 2026-11-10)",
            "deepseek-flash": {"model_version": "DeepSeek-V4.1-Flash-1017",
                               "input_cache_hit_per_1M": {"peak": 0.006, "off_peak": 0.003},
                               "input_cache_miss_per_1M": {"peak": 0.3, "off_peak": 0.15},
                               "output_per_1M": {"peak": 1.2, "off_peak": 0.6},
                               "currency": "USD"},
        },
        "key_loaded": None, "models": None, "tests": {}, "cost_estimate": {},
    }

    key = load_key()
    result["key_loaded"] = {"ok": True, "length": len(key), "masked": "sk-***（已隐藏，仅存长度）"}

    # /models（不计费）
    t0 = time.perf_counter()
    r = requests.get(f"{BASE_URL}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    models = [m.get("id") for m in r.json().get("data", [])] if r.status_code == 200 else []
    result["models"] = {"http": r.status_code, "elapsed_s": round(time.perf_counter() - t0, 3),
                        "contains_deepseek_flash": "deepseek-flash" in models,
                        "matched_ids": [m for m in models if "flash" in m]}

    # 测试 1：中文文本生成（非流式）
    p1 = {"model": "deepseek-flash", "temperature": 0,
          "messages": [{"role": "user", "content": "用一句话（不超过30字）说明什么是 LangGraph。"}]}
    t1 = chat(key, p1, tag="chinese_gen")
    ok1 = t1["http"] == 200 and "LangGraph" in t1["body"]["choices"][0]["message"]["content"]
    result["tests"]["chinese_gen"] = {"pass": ok1, "http": t1["http"], "elapsed_s": t1["elapsed_s"],
                                      "reply": t1["body"]["choices"][0]["message"]["content"],
                                      "usage": mask_usage(t1["body"].get("usage"))}

    # 测试 2：JSON 结构化输出
    p2 = {"model": "deepseek-flash", "temperature": 0,
          "response_format": {"type": "json_object"},
          "messages": [{"role": "system", "content": "你是一个只输出 JSON 的助手。"},
                       {"role": "user", "content": '把"北京今天晴，气温5到12摄氏度"提取为 JSON，字段：city, weather, low_c, high_c'}]}
    t2 = chat(key, p2, tag="json_output")
    content2 = t2["body"]["choices"][0]["message"]["content"] if t2["http"] == 200 else ""
    parsed2, json_ok = None, False
    try:
        parsed2 = json.loads(content2)
        json_ok = parsed2.get("city") == "北京" and parsed2.get("weather") == "晴"
    except Exception:
        pass
    result["tests"]["json_output"] = {"pass": t2["http"] == 200 and json_ok, "http": t2["http"],
                                      "elapsed_s": t2["elapsed_s"], "raw": content2, "parsed": parsed2,
                                      "usage": mask_usage(t2["body"].get("usage"))}

    # 测试 3：Tool Calling
    tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "查询指定城市的天气",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "description": "城市名"}}, "required": ["city"]}}}]
    p3 = {"model": "deepseek-flash", "temperature": 0, "tools": tools,
          "messages": [{"role": "user", "content": "上海现在天气怎么样？"}]}
    t3 = chat(key, p3, tag="tool_calling")
    msg3 = t3["body"]["choices"][0]["message"] if t3["http"] == 200 else {}
    calls = msg3.get("tool_calls") or []
    tool_ok = bool(calls) and calls[0]["function"]["name"] == "get_weather" and \
        json.loads(calls[0]["function"]["arguments"]).get("city") == "上海"
    result["tests"]["tool_calling"] = {"pass": t3["http"] == 200 and tool_ok, "http": t3["http"],
                                       "elapsed_s": t3["elapsed_s"],
                                       "tool_calls": calls, "usage": mask_usage(t3["body"].get("usage"))}

    # 测试 4：Streaming（含 usage）
    p4 = {"model": "deepseek-flash", "temperature": 0, "stream": True,
          "stream_options": {"include_usage": True},
          "messages": [{"role": "user", "content": "用一句话说明什么是 RAG。"}]}
    t0 = time.perf_counter()
    chunks, usage4, finish = [], None, None
    with requests.post(f"{BASE_URL}/chat/completions", json=p4, stream=True,
                       headers={"Authorization": f"Bearer {key}"}, timeout=60) as r4:
        for line in r4.iter_lines():
            if not line or not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            j = json.loads(data)
            if j.get("usage"):
                usage4 = j["usage"]
            for c in j.get("choices", []):
                if c.get("delta", {}).get("content"):
                    chunks.append(c["delta"]["content"])
                if c.get("finish_reason"):
                    finish = c["finish_reason"]
    stream_text = "".join(chunks)
    result["tests"]["streaming"] = {"pass": bool(stream_text) and finish == "stop",
                                    "elapsed_s": round(time.perf_counter() - t0, 3),
                                    "text": stream_text, "finish_reason": finish,
                                    "chunk_count": len(chunks), "usage": mask_usage(usage4)}

    # 异常模拟（均不产生计费、不触发真实限流）
    # 4a. 伪造 Key → 401/402 鉴权失败
    r_bad = requests.post(f"{BASE_URL}/chat/completions",
                          json={"model": "deepseek-flash", "messages": [{"role": "user", "content": "hi"}]},
                          headers={"Authorization": "Bearer sk-invalid-fake-key-for-testing"}, timeout=30)
    result["tests"]["auth_failure_sim"] = {"expected_4xx": r_bad.status_code in (401, 402, 400),
                                           "http": r_bad.status_code, "body_head": r_bad.text[:120]}
    # 4b. 极小超时 → 客户端超时异常
    try:
        chat(key, p1, timeout=0.001, tag="timeout_sim")
        timeout_ok = False
    except requests.Timeout:
        timeout_ok = True
    result["tests"]["timeout_sim"] = {"raised_timeout": timeout_ok}

    # 费用估算（按实测 usage，当前时段价）
    def cost(u):
        if not u:
            return None
        hit = u.get("prompt_cache_hit_tokens", 0) or 0
        miss = (u.get("prompt_tokens", 0) or 0) - hit
        out = u.get("completion_tokens", 0) or 0
        tier = "peak" if peak else "off_peak"
        pr = result["pricing_reference"]["deepseek-flash"]
        return {"input_tokens": u.get("prompt_tokens"), "output_tokens": out,
                "cache_hit_tokens": hit, "cache_miss_tokens": miss,
                "cost_usd": round(miss / 1e6 * pr["input_cache_miss_per_1M"][tier]
                                  + hit / 1e6 * pr["input_cache_hit_per_1M"][tier]
                                  + out / 1e6 * pr["output_per_1M"][tier], 8),
                "tier": tier}
    total = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "cache_hit_tokens": 0}
    for name in ("chinese_gen", "json_output", "tool_calling", "streaming"):
        c = cost(result["tests"][name].get("usage"))
        result["cost_estimate"][name] = c
        if c:
            total["cost_usd"] += c["cost_usd"]
            total["input_tokens"] += c["input_tokens"] or 0
            total["output_tokens"] += c["output_tokens"]
            total["cache_hit_tokens"] += c["cache_hit_tokens"]
    total["cost_usd"] = round(total["cost_usd"], 8)
    result["cost_estimate"]["total_4_calls"] = total

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"key_loaded": result["key_loaded"],
                      "models": result["models"],
                      "peak": result["peak_check"],
                      "tests": {k: v.get("pass", v) for k, v in result["tests"].items()},
                      "cost": result["cost_estimate"]["total_4_calls"]}, ensure_ascii=False, indent=2))
    print("saved:", OUT)


if __name__ == "__main__":
    main()
