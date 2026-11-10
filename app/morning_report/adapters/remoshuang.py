"""热摸爽每日早报接入（发现线索与跨源核对，不当精确时间主证据，V0.6.1 §4.3）。

- 公开 /daily/YYYY-MM-DD.md，约 30 条，含 AI 摘要与原始链接。
- 统计周期 05:00–05:00，与晨报窗口错位；多数条目无原始发布时间 → published_at=None（线索级）。
- 优先公开 MD，不使用面向站内的私有 api/* 路径。
"""

from __future__ import annotations

import logging
import re

from . import NewsCandidate
from .http_common import fetch_text

logger = logging.getLogger(__name__)

AI_KEYWORDS = ("AI", "大模型", "OpenAI", "Claude", "Gemini", "LLM", "智能体", "Agent",
               "深度学习", "开源模型", "GPT", "DeepSeek", "GitHub")
INTL_KEYWORDS = ("美国", "俄罗斯", "俄", "乌克兰", "伊朗", "以色列", "特朗普", "普京",
                 "欧盟", "北约", "联合国", "日本", "韩国", "印度", "中东", "国际油价", "美联储")
ENTRY_RE = re.compile(r"^\d+\.\s+\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)\s*$", re.M)


def classify(title: str) -> str:
    if any(k in title for k in AI_KEYWORDS):
        return "ai"
    if any(k in title for k in INTL_KEYWORDS):
        return "international"
    return "domestic"


def parse_daily(md: str, daily_date: str) -> list[NewsCandidate]:
    out: list[NewsCandidate] = []
    for m in ENTRY_RE.finditer(md):
        title = m.group("title").strip()
        out.append(NewsCandidate(
            category=classify(title),
            title=title,
            summary="",  # 摘要为聚合方 AI 生成，保留 raw 中，正文不直接当事实
            source_name="热摸爽",
            source_url=m.group("url").strip(),
            published_at=None,  # 无逐条原始发布时间
            adapter="remoshuang",
            raw={"daily_date": daily_date, "time_confidence": "day_only"},
        ))
    return out


def fetch_daily(daily_date: str) -> list[NewsCandidate]:
    """daily_date=YYYY-MM-DD（取当期与上一期两份，覆盖 05:00 错位）由调用方决定。"""

    url = f"https://remoshuang.com/daily/{daily_date}.md"
    return parse_daily(fetch_text(url), daily_date)
