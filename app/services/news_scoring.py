"""资讯评分纯函数（PRD §2.2 / ARCH §3.2）：可独立测试、无 IO、无 LLM。

综合分 = norm_heat（按来源归一化 0-1）× 来源权重 × 时效衰减。
各来源原始热度指标禁止混用，必须先经本模块归一化。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# ---- 去重 ----

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "mc_cid", "mc_eid", "ref"}


def normalize_url(url: str) -> str:
    """URL 规范化：scheme/host 小写、去 fragment、去跟踪参数、参数排序、去尾斜杠。"""

    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    if not host:
        return url.strip()
    port = parts.port
    netloc = host + (f":{port}" if port and port not in (80, 443) else "")
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in _TRACKING_PARAMS
        )
    )
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def title_hash(title: str) -> str:
    """标题哈希去重（空白压缩 + 小写 + sha1）。"""

    normalized = " ".join((title or "").split()).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


# ---- 热度归一化 ----


def norm_heat_hn(points: float) -> float:
    """HN points → [0,1)：points/(points+100)，单调；零互动为 0（HN 有真实指标）。"""

    points = max(float(points), 0.0)
    return round(points / (points + 100.0), 4)


def norm_heat_rss() -> float:
    """RSS 无互动指标：中性默认 0.5，不视为零价值（PRD §2.2）。"""

    return 0.5


def norm_heat(kind: str, heat_raw: float) -> float:
    if kind == "hn":
        return norm_heat_hn(heat_raw)
    return norm_heat_rss()


# ---- 时效衰减：半衰期 48 小时的指数衰减 ----

HALF_LIFE = timedelta(hours=48)


def age_decay(published_at: datetime, now: datetime | None = None) -> float:
    """发布越久衰减越小；未来发布时间按 1.0 计；返回值 (0,1]。"""

    now = now or datetime.now(tz=timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age = now - published_at.astimezone(timezone.utc)
    if age <= timedelta(0):
        return 1.0
    # 下限 0.01：极旧资讯保留微小热度，避免四舍五入后直接归零
    return max(round(0.5 ** (age / HALF_LIFE), 4), 0.01)


# ---- 主题相关度：规则关键词匹配（可解释、可调整，不用 LLM） ----

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ai": ("llm", "gpt", "gemini", "claude", "大模型", "模型", "transformer", "diffusion", "openai", "anthropic", "hugging face", "深度学习", "神经网络", "推理模型"),
    "agent": ("agent", "智能体", "agents", "multi-agent", "autonomous", "langgraph", "langchain", "crewai", "tool use", "function calling", "mcp"),
    "ai_coding": ("cursor", "copilot", "code assistant", "ai 编程", "ai编程", "ai coding", "aider", "codeium", "windsurf", "devin", "代码生成", "编程工具"),
    "python": ("python", "pypi", "django", "flask", "fastapi", "pandas", "numpy"),
    "typescript": ("typescript", "javascript", "node.js", "nodejs", "react", "vite", "deno", "bun", "前端", "type system"),
    "engineering": ("性能", "performance", "架构", "refactor", "重构", "testing", "测试", "ci/cd", "devops", "database", "数据库", "并发", "缓存", "cache", "开源社区"),
    "opensource": ("开源", "open source", "github", "release", "发布", "changelog", "版本", "框架", "framework", "工具库", "library"),
}


def topic_of(title: str, summary: str = "") -> tuple[str, float]:
    """返回 (主题, 相关度)。标题命中=1.0，摘要命中=0.5；多主题按定义优先级取首个。"""

    text_title = (title or "").lower()
    text_summary = (summary or "").lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in text_title for keyword in keywords):
            return topic, 1.0
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in text_summary for keyword in keywords):
            return topic, 0.5
    return "other", 0.0


def compute_score(norm_heat_value: float, weight: float, published_at: datetime, now: datetime | None = None) -> float:
    """综合分 = 归一化热度 × 来源权重 × 时效衰减。"""

    return round(norm_heat_value * max(weight, 0.0) * age_decay(published_at, now), 4)


# ---- 过期判定（PRD §2.5：未收藏 >7 天进入待清理；已收藏豁免） ----

RETENTION_DAYS = 7


def is_expired(published_at: datetime, now: datetime | None = None, *, is_favorite: bool = False, days: int = RETENTION_DAYS) -> bool:
    if is_favorite:
        return False
    now = now or datetime.now(tz=timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return now - published_at.astimezone(timezone.utc) > timedelta(days=days)
