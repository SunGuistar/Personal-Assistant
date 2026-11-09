"""T4：AIHOT（爱热榜/AI 资讯聚合）机制核查（LIVE 探测 + STATIC）。

验证：是否有可访问 API/数据接口、覆盖领域、更新频率、热度指标语义、
来源可溯性、正文获取、限流。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import save_result, Timer

UA = {"User-Agent": "personal-assistant-tv2-probe/0.1"}
out = {}

CANDIDATES = [
    ("aihot_cn", "https://www.aihot.cn/"),
    ("aihot_cc", "https://aihot.cc/"),
    ("aihot_app", "https://www.aihot.com/"),
]


def probe_site(name, url):
    r = {"url": url}
    try:
        with Timer() as t:
            with httpx.Client(timeout=15, headers=UA, follow_redirects=True) as c:
                resp = c.get(url)
        r["elapsed_s"] = t.seconds
        r["status"] = resp.status_code
        r["final_url"] = str(resp.url)
        r["bytes"] = len(resp.text)
        if resp.status_code != 200:
            r["ok"] = False
            return r
        soup = BeautifulSoup(resp.text, "lxml")
        r["page_title"] = (soup.title.get_text(strip=True) if soup.title else "")[:100]
        text = soup.get_text(" ", strip=True)
        r["text_sample"] = text[:300]
        # 探测页面中的 API 线索与热度字段
        scripts = " ".join(s.get("src", "") for s in soup.find_all("script"))
        api_hints = sorted(set(re.findall(r"[\"'](/api/[^\"']+)[\"']", resp.text)))[:10]
        r["api_hints"] = api_hints
        r["mentions_heat"] = bool(re.search(r"热度|热榜|heat|hot|score|score", text[:5000], re.I))
        r["mentions_ai_topics"] = [kw for kw in ["大模型", "LLM", "OpenAI", "Agent", "RAG", "论文"]
                                   if kw in text[:8000]]
        links = [a.get("href", "") for a in soup.find_all("a")][:200]
        ext = [l for l in links if l.startswith("http") and "aihot" not in l]
        r["external_source_links_count"] = len(ext)
        r["external_source_samples"] = ext[:8]
        r["ok"] = True
    except Exception as e:
        r["ok"] = False
        r["error"] = f"{type(e).__name__}: {e}"[:300]
    return r


for name, url in CANDIDATES:
    out[name] = probe_site(name, url)
    print(name, out[name].get("ok"), out[name].get("status"))

save_result("t4_aihot", out)
print("T4 probe done")
