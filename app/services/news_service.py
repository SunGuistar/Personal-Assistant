"""资讯中心业务逻辑（PRD §2.2：近期热门 TOP 10 + 外部导航，2026-11 最终版）。

- 默认来源种子（D6）：首次启动写入 news_sources（7 个已验证来源）；
- 刷新：TaskRunner 后台任务逐源抓取（单源失败不影响整体），URL 规范化
  + 标题哈希双重去重，已存在条目跳过；刷新只增不删，失败保留旧缓存；
- TOP 10：纯查询（rank_top_items），24h 优先 / 72h 回退 / 单来源上限，
  首页与资讯页共用同一份缓存，不因页面加载触发抓取；
- 收藏/已读/筛选等平台功能已取消（PRD §2.2），库中字段保留但业务零读写。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.news_common import NewsAdapterError, RawNewsItem
from ..adapters.news_hn import HackerNewsAdapter
from ..adapters.news_rss import RssAdapter
from ..models import NewsItem, NewsSource, Task
from .news_scoring import (
    compute_score,
    norm_heat,
    normalize_url,
    rank_top_items,
    title_hash,
    topic_of,
)

logger = logging.getLogger(__name__)

REFRESH_KIND = "news.refresh"

# D6 默认来源种子（kind rss/hn；中文名备注仅用于展示）。
# endpoint 以真实可访问为准（冒烟验证见阶段 4 汇报）。
DEFAULT_SOURCES: tuple[dict, ...] = (
    {"name": "Hacker News", "kind": "hn", "endpoint": "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30", "weight": 1.0},
    {"name": "GitHub Blog", "kind": "rss", "endpoint": "https://github.blog/feed/", "weight": 1.0},
    {"name": "Python Insider", "kind": "rss", "endpoint": "https://blog.python.org/feeds/posts/default?alt=rss", "weight": 1.0},
    {"name": "TypeScript Blog", "kind": "rss", "endpoint": "https://devblogs.microsoft.com/typescript/feed/", "weight": 1.0},
    {"name": "OpenAI News", "kind": "rss", "endpoint": "https://openai.com/news/rss.xml", "weight": 1.2},
    {"name": "阮一峰的网络日志", "kind": "rss", "endpoint": "https://www.ruanyifeng.com/blog/atom.xml", "weight": 1.0},
    {"name": "Hugging Face Blog", "kind": "rss", "endpoint": "https://huggingface.co/blog/feed.xml", "weight": 1.1},
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- 来源 ----------

def ensure_default_sources(session: Session) -> None:
    """首次运行写入默认来源种子（幂等：以 name 判重）。

    来源管理 API 已随平台功能取消（PRD §2.2），如需增删来源直接维护
    news_sources 表；enabled/weight 字段保留。
    """

    existing = session.execute(select(NewsSource.name)).scalars().all()
    known = set(existing)
    for seed in DEFAULT_SOURCES:
        if seed["name"] not in known:
            session.add(NewsSource(**seed))
    session.commit()


def _make_adapter(source: NewsSource, client: httpx.Client | None):
    if source.kind == "hn":
        return HackerNewsAdapter(source.endpoint, client=client)
    return RssAdapter(source.endpoint, client=client)


# ---------- 入库 ----------

def upsert_items(session: Session, source: NewsSource, raw_items: list[RawNewsItem]) -> int:
    """入库新条目；URL 规范化唯一 + 标题哈希去重。已存在条目完全跳过（保留收藏/已读）。"""

    inserted = 0
    for raw in raw_items:
        url = normalize_url(raw.url)
        exists = session.execute(select(NewsItem.id).where(NewsItem.url == url)).first()
        if exists:
            continue
        digest = title_hash(raw.title)
        title_clash = session.execute(select(NewsItem.id).where(NewsItem.title_hash == digest)).first()
        if title_clash:
            continue
        topic, _relevance = topic_of(raw.title, raw.raw_summary)
        published = raw.published_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        heat = norm_heat(source.kind, raw.heat_raw)
        item = NewsItem(
            title=raw.title[:512],
            url=url,
            source=source.name,
            source_id=source.id,
            topic=topic,
            published_at=published,
            raw_summary=raw.raw_summary,
            heat_raw=raw.heat_raw,
            norm_heat=heat,
            score=compute_score(heat, source.weight, raw.published_at),
            title_hash=digest,
            fetched_at=_now(),
        )
        session.add(item)
        inserted += 1
    session.commit()
    return inserted


# ---------- 刷新 ----------

def refresh_all(session: Session, *, client: httpx.Client | None = None, progress_cb=None) -> dict:
    """逐源抓取入库；单源失败记录后继续，不影响其他来源。"""

    ensure_default_sources(session)
    sources = session.execute(
        select(NewsSource).where(NewsSource.enabled == 1).order_by(NewsSource.id)
    ).scalars().all()
    total_new = 0
    fetched = 0
    failures: list[dict] = []
    for index, source in enumerate(sources):
        try:
            adapter = _make_adapter(source, client)
            raw_items = adapter.fetch()
            total_new += upsert_items(session, source, raw_items)
            fetched += len(raw_items)
        except Exception as exc:  # 单源失败不拖垮整体（AGENTS §6：错误落任务表由调用方兜底）
            message = f"{type(exc).__name__}: {exc}"[:300]
            failures.append({"source": source.name, "error": message})
            logger.warning("news source %s refresh failed: %s", source.name, message)
        if progress_cb:
            progress_cb(int((index + 1) / max(len(sources), 1) * 100))
    return {
        "refreshed_at": _now(),
        "sources": len(sources),
        "fetched": fetched,
        "new_items": total_new,
        "failures": failures,
    }


def last_refresh(session: Session) -> dict | None:
    """最近一次成功刷新的结果（来自任务表），无则 None。"""

    row = session.execute(
        select(Task)
        .where(Task.kind == REFRESH_KIND, Task.status == "success")
        .order_by(Task.id.desc())
    ).scalars().first()
    if row is None or not row.result_json:
        return None
    import json

    try:
        result = json.loads(row.result_json)
    except ValueError:
        return None
    return {
        "refreshed_at": result.get("refreshed_at"),
        "new_items": result.get("new_items"),
        "sources": result.get("sources"),
        "failures": result.get("failures", []),
    }


# ---------- 查询与状态 ----------

def item_to_dict(item: NewsItem) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "source_id": item.source_id,
        "topic": item.topic,
        "published_at": item.published_at,
        "raw_summary": item.raw_summary,
        "norm_heat": item.norm_heat,
        "score": item.score,
        "is_favorite": bool(item.is_favorite),
        "is_read": bool(item.is_read),
        "fetched_at": item.fetched_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


# ---------- 查询：TOP 10 榜单（首页与资讯页共用同一份缓存数据） ----------

def top_items(session: Session, *, limit: int = 10) -> dict:
    """从本地缓存生成 TOP 榜单；不足 limit 按实际数量返回。

    排行榜是纯查询：不触发抓取，首页加载不会被外部来源阻塞。
    """

    rows = session.execute(select(NewsItem).order_by(NewsItem.published_at.desc())).scalars().all()
    candidates = [item_to_dict(row) for row in rows]
    ranked = rank_top_items(candidates, limit=limit)
    return {
        "items": ranked,
        "total": len(ranked),
        "generated_at": _now(),
    }
