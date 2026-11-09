"""T8：DeepSeek / DashScope API 验证（STATIC 官方文档 + LIVE 有限调用）。

文档核查结论（2026-11，官方 api-docs.deepseek.com）：
- 产品目标模型版本 DeepSeek-V4.1-Flash-1017 真实存在；公开 API 模型标识为
  `deepseek-flash`（旧名 deepseek-v4-flash 仍接受但后端已指向 V4.1）。
- 高峰时段：周一至周五（不含中国法定节假日）01:00-04:00 与 06:00-10:00 UTC，
  即北京时间 09:00-12:00、14:00-18:00；其余为低谷（含周末/节假日全天）。
- deepseek-flash 支持 JSON Output、Tool Calls、Responses API、Vision；1M 上下文。

实测（有 key 才执行，各 1-2 次）：
- DeepSeek：/models 列表确认 deepseek-flash；chat completion 验证 JSON 输出、
  tool calling、usage 中 prompt_cache_hit_tokens。
- 允许时段检查函数：跨时段断言（模拟时钟）。
- DashScope：当前配置模型（llm_config.json）短调用验证可用 + 结构化输出。
- 质量评价 API 独立性：用不同模型的一次独立调用验证。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_hub_env, save_result, Timer

env = load_hub_env()
out = {"env_presence": env,
       "official_docs_static": {
           "target_model_version": "DeepSeek-V4.1-Flash-1017（真实存在）",
           "public_api_model_id": "deepseek-flash",
           "legacy_ids": "deepseek-v4-flash / deepseek-v4-flash-vision-exp 仍被接受，后端为 V4.1-Flash-1017",
           "product_naming_verdict": "产品文档的 DeepSeek-V4.1-Flash-1017 是模型版本名，不是 API 标识；"
                                     "调用时应传 deepseek-flash（产品文档已注明‘实际 API 标识由 Kimi Code 核实’）",
           "peak_utc": ["01:00-04:00", "06:00-10:00"],
           "peak_beijing": ["09:00-12:00", "14:00-18:00"],
           "off_peak": "其余时间 + 周末/中国法定节假日全天；低谷价为高峰价一半",
           "features": ["JSON Output", "Tool Calls", "Responses API", "Vision", "1M context", "384K max output"],
           "concurrency_limit": 2500,
           "source": "https://api-docs.deepseek.com/quick_start/pricing（2026-11-08 抓取）",
       }}

# ---- 允许时段检查（纯函数 + 断言）----
BJ = timezone(timedelta(hours=8))


def is_off_peak(dt_bj: datetime) -> bool:
    """dt_bj 须为北京时间。高峰=工作日 9-12、14-18（UTC 1-4、6-10）。"""
    if dt_bj.tzinfo is None:
        dt_bj = dt_bj.replace(tzinfo=BJ)
    dt_bj = dt_bj.astimezone(BJ)
    weekday = dt_bj.weekday()  # 0=Mon
    h = dt_bj.hour
    peak = (9 <= h < 12) or (14 <= h < 18)
    return not (weekday < 5 and peak)


checks = {
    "周一 08:00 低谷(可生成)": is_off_peak(datetime(2026, 11, 9, 8, 0, tzinfo=BJ)) is True,
    "周一 10:00 高峰(禁止)": is_off_peak(datetime(2026, 11, 9, 10, 0, tzinfo=BJ)) is False,
    "周一 15:00 高峰(禁止)": is_off_peak(datetime(2026, 11, 9, 15, 0, tzinfo=BJ)) is False,
    "周一 22:00 低谷": is_off_peak(datetime(2026, 11, 9, 22, 0, tzinfo=BJ)) is True,
    "周六 10:00 低谷(周末全天)": is_off_peak(datetime(2026, 11, 7, 10, 0, tzinfo=BJ)) is True,
    "跨时区输入 UTC 00:30(=北京 08:30 低谷)": is_off_peak(datetime(2026, 11, 9, 0, 30, tzinfo=timezone.utc)) is True,
}
out["off_peak_checker"] = {"checks": checks, "all_pass": all(checks.values())}

# ---- DeepSeek LIVE ----
ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
out["deepseek"] = {"key_present": bool(ds_key)}
if ds_key:
    H = {"Authorization": f"Bearer {ds_key}"}
    try:
        with httpx.Client(timeout=30, headers=H) as c:
            models = c.get("https://api.deepseek.com/models").json()
            ids = [m.get("id") for m in models.get("data", [])]
            out["deepseek"]["models_endpoint_ok"] = True
            out["deepseek"]["model_ids"] = ids
            out["deepseek"]["deepseek_flash_listed"] = "deepseek-flash" in ids

            # JSON 输出 + usage 字段
            r1 = c.post("https://api.deepseek.com/chat/completions", json={
                "model": "deepseek-flash",
                "messages": [{"role": "user", "content": "用 JSON 回答：{\\\"ok\\\": true} 只输出 JSON"}],
                "max_tokens": 60, "response_format": {"type": "json_object"}})
            j1 = r1.json()
            u1 = j1.get("usage", {})
            out["deepseek"]["json_output_call"] = {
                "ok": r1.status_code == 200,
                "content_head": (j1.get("choices", [{}])[0].get("message", {}).get("content", "")[:60]),
                "usage_keys": sorted(u1.keys()),
                "prompt_cache_hit_tokens": u1.get("prompt_cache_hit_tokens"),
                "total_tokens": u1.get("total_tokens"),
            }
            # Tool calling
            r2 = c.post("https://api.deepseek.com/chat/completions", json={
                "model": "deepseek-flash",
                "messages": [{"role": "user", "content": "北京现在天气如何？请调用工具查询。"}],
                "tools": [{"type": "function", "function": {
                    "name": "get_weather", "description": "查询城市天气",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                                   "required": ["city"]}}}],
                "max_tokens": 100})
            j2 = r2.json()
            msg = j2.get("choices", [{}])[0].get("message", {})
            tc = msg.get("tool_calls")
            out["deepseek"]["tool_calling"] = {
                "ok": r2.status_code == 200 and bool(tc),
                "tool_name": tc[0]["function"]["name"] if tc else None,
                "arguments": tc[0]["function"]["arguments"] if tc else None,
            }
            out["deepseek"]["actual_calls_made"] = 3
    except Exception as e:
        out["deepseek"]["error"] = f"{type(e).__name__}: {e}"[:300]

# ---- DashScope LIVE（经 OpenAI 兼容端点；新版模型在 dashscope SDK 旧端点报 url error）----
dash_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
out["dashscope"] = {"key_present": bool(dash_key)}
if dash_key:
    try:
        H2 = {"Authorization": f"Bearer {dash_key}"}
        cfg = json.loads(Path(r"E:/wechat-LangGraph/app/wechat_agent/llm_config.json").read_text(encoding="utf-8"))
        out["dashscope"]["configured_model"] = cfg.get("default_model")
        out["dashscope"]["note_sdk_issue"] = ("qwen3-vl-plus 在 dashscope SDK 旧 text-generation 端点报 400 url error；"
                                              "OpenAI 兼容端点调用正常。langchain-openai ChatOpenAI 可直接使用。")

        def ds_call(model, content, max_tokens=30):
            with Timer() as t:
                r = httpx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                               headers=H2, timeout=30, json={
                                   "model": model,
                                   "messages": [{"role": "user", "content": content}],
                                   "max_tokens": max_tokens, "temperature": 0.0})
            j = r.json()
            ok = r.status_code == 200 and bool(j.get("choices"))
            return {"ok": ok, "status": r.status_code,
                    "output_head": (j["choices"][0]["message"]["content"][:40] if ok
                                    else str(j.get("error", {}))[:150]),
                    "usage": j.get("usage") if ok else None,
                    "elapsed_s": t.seconds}

        # 当前配置模型（经兼容端点）
        out["dashscope"]["configured_model_call"] = ds_call(cfg.get("default_model", "qwen3-vl-plus"),
                                                            "回复两个字：正常")
        # 免费模型候选
        out["dashscope"]["qwen_flash_free_call"] = ds_call("qwen-flash", "回复两个字：正常")
        # 付费模型配额状态（探测，不实际消耗）
        out["dashscope"]["qwen_plus_quota_probe"] = ds_call("qwen-plus", "hi", max_tokens=5)
        # 质量评价独立性：独立模型独立调用
        out["dashscope"]["independent_eval_call"] = ds_call("qwen-flash", "用1-10给『今天天气不错』打分，只输出数字", 10)
        # 结构化输出（JSON mode）
        r = httpx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                       headers=H2, timeout=30, json={
                           "model": "qwen-flash",
                           "messages": [{"role": "user", "content": "输出 JSON：{\"score\": 8}"}],
                           "response_format": {"type": "json_object"}, "max_tokens": 30})
        out["dashscope"]["json_output"] = {"ok": r.status_code == 200,
                                           "body_head": r.text[:80]}
    except Exception as e:
        out["dashscope"]["error"] = f"{type(e).__name__}: {e}"[:300]

save_result("t8_llm_api", out)
print("T8 done. ds key:", bool(ds_key), "| dash:", bool(dash_key),
      "| off-peak all:", out["off_peak_checker"]["all_pass"])
