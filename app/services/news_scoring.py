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


# ---- TOP 10 排名（纯函数：确定性、可解释，同输入同输出） ----

RELEVANCE_BONUS = 0.5  # 有效分 = 综合分 × (1 + 0.5 × 主题相关度)
PREFER_WINDOW = timedelta(hours=24)  # 优先最近 24 小时
FALLBACK_WINDOW = timedelta(hours=72)  # 不足时回退到 72 小时
DEFAULT_SOURCE_CAP = 4  # 单来源上榜上限（多样性约束）


def effective_score(score: float, title: str, summary: str = "") -> float:
    """有效分 = 综合分 × (1 + 相关度奖励)，主题相关性真实参与排序。"""

    _, relevance = topic_of(title, summary)
    return round(score * (1 + RELEVANCE_BONUS * relevance), 4)


def rank_top_items(
    items: list[dict],
    *,
    now: datetime | None = None,
    limit: int = 10,
    source_cap: int = DEFAULT_SOURCE_CAP,
) -> list[dict]:
    """从候选条目生成 TOP 榜单。

    items 元素需含: id, title, url, source, published_at(UTC ISO), raw_summary, score。
    规则：有效分（含主题奖励）降序 → 发布时间降序 → id 升序（保证稳定）；
    先取最近 24 小时且单来源不超上限，不足 limit 再回退到 72 小时补足；
    仍不足按实际数量返回。返回元素附加 effective_score 与 rank。
    """

    now = now or datetime.now(tz=timezone.utc)

    def parse(item: dict) -> tuple[datetime, float]:
        published = datetime.fromisoformat(item["published_at"])
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return published.astimezone(timezone.utc), effective_score(
            float(item.get("score", 0.0)), item.get("title", ""), item.get("raw_summary", "")
        )

    decorated: list[tuple[datetime, float, int, dict]] = []
    seen_urls: set[str] = set()
    for item in items:
        url = item.get("url", "")
        if not url or url in seen_urls:  # 相同文章不重复上榜
            continue
        seen_urls.add(url)
        published, eff = parse(item)
        decorated.append((published, eff, int(item.get("id", 0)), item))

    # 排序键：有效分 ↓、发布时间 ↓、id ↑（同缓存多次请求排名稳定）
    decorated.sort(key=lambda row: (-row[1], -row[0].timestamp(), row[2]))

    selected: list[tuple[datetime, float, int, dict]] = []
    per_source: dict[str, int] = {}  # 上限跨窗口累计：回退窗口不重置来源配额

    def take(window: timedelta) -> None:
        for row in decorated:
            if len(selected) >= limit:
                return
            if row in selected:
                continue
            if now - row[0] > window:  # 超出窗口跳过；未来发布时间按最新处理
                continue
            source = row[3].get("source", "")
            if per_source.get(source, 0) >= source_cap:
                continue
            per_source[source] = per_source.get(source, 0) + 1
            selected.append(row)

    take(PREFER_WINDOW)
    if len(selected) < limit:
        take(FALLBACK_WINDOW)

    # 最终榜单按排名键重排（选取顺序受窗口/配额影响，不代表最终名次）
    selected.sort(key=lambda row: (-row[1], -row[0].timestamp(), row[2]))

    ranked: list[dict] = []
    for rank, (_published, eff, _id, item) in enumerate(selected[:limit], start=1):
        entry = dict(item)
        entry["effective_score"] = eff
        entry["rank"] = rank
        ranked.append(entry)
    return ranked
