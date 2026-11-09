"""T11：NewsAPI 专项验证（LIVE 无 key 探测 + 官方文档核查）。

- 检测 NEWS_API_KEY 是否存在（不打印值）。
- 无 key 时调用 /v2/top-headlines?country=cn 观察 401（证明端点可达+鉴权生效）。
- 有 key 则做 1 次真实 country=cn 调用验证中文/国内覆盖与字段。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import save_result, Timer, load_hub_env

env_presence = load_hub_env()
key = os.environ.get("NEWS_API_KEY", "").strip()
out = {"news_api_key_present": bool(key), "env_presence": env_presence}

if key:
    with Timer() as t:
        with httpx.Client(timeout=20) as c:
            resp = c.get("https://newsapi.org/v2/top-headlines",
                         params={"country": "cn", "pageSize": 10, "apiKey": key})
    data = resp.json()
    arts = data.get("articles", [])
    out["live_call"] = {
        "ok": resp.status_code == 200 and data.get("status") == "ok",
        "status": resp.status_code, "total_results": data.get("totalResults"),
        "items": len(arts),
        "fields": sorted(arts[0].keys()) if arts else [],
        "has_content_field": bool(arts and arts[0].get("content")),
        "sample_masked": [{"title": a.get("title", "")[:50], "source": (a.get("source") or {}).get("name", ""),
                           "publishedAt": a.get("publishedAt", "")} for a in arts[:5]],
        "elapsed_s": t.seconds,
    }
else:
    # 端点可达性 + 401 行为（异常也要记录为 BLOCKED 证据）
    try:
        with Timer() as t:
            with httpx.Client(timeout=15) as c:
                resp = c.get("https://newsapi.org/v2/top-headlines",
                             params={"country": "cn", "apiKey": "invalid-tv2-probe"})
        out["no_key_probe"] = {
            "endpoint_reachable": True, "status": resp.status_code,
            "error_body_masked": {k: v for k, v in resp.json().items() if k in ("status", "code", "message")},
            "elapsed_s": t.seconds,
            "note": "无可用凭据；官方文档结论见 reports/stage_1_data_sources.md",
        }
    except Exception as e:
        out["no_key_probe"] = {
            "endpoint_reachable": False,
            "error": f"{type(e).__name__}: {e}"[:150],
            "note": "本机网络无法访问 newsapi.org；NEWS_API_KEY 也未配置。双重 BLOCKED。",
        }

save_result("t11_newsapi", out)
print("T11 probe done, key present:", bool(key))
