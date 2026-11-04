"""资讯中心业务逻辑（PRD §2.2 / ARCH §3.2）。纯函数式 service：接收 Session，不依赖 FastAPI。

- 默认来源种子（D6）：首次启动写入 news_sources，可在设置中增删改；
- 刷新：逐源抓取（单源失败不影响整体），URL 规范化 + 标题哈希双重去重，
  已存在的条目跳过（保留收藏/已读状态）；
- 过期：仅提供判定与查询（供阶段 5 清理候选生成），本阶段不做任何删除。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters.news_common import NewsAdapterError, RawNewsItem
from ..adapters.news_hn import HackerNewsAdapter
from ..adapters.news_rss import RssAdapter
from ..exceptions import DomainError, NotFoundError
from ..models import NewsItem, NewsSource, Task
from .news_scoring import (
    compute_score,
    is_expired,
    norm_heat,
    normalize_url,
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
    """首次运行写入默认来源种子（幂等：以 name 判重）。"""

    existing = session.execute(select(NewsSource.name)).scalars().all()
    known = set(existing)
    for seed in DEFAULT_SOURCES:
        if seed["name"] not in known:
            session.add(NewsSource(**seed))
    session.commit()


def source_to_dict(source: NewsSource) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "kind": source.kind,
        "endpoint": source.endpoint,
        "enabled": bool(source.enabled),
        "weight": source.weight,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


def list_sources(session: Session) -> list[dict]:
    ensure_default_sources(session)
    rows = session.execute(select(NewsSource).order_by(NewsSource.id)).scalars().all()
    return [source_to_dict(row) for row in rows]


def create_source(session: Session, *, name: str, kind: str, endpoint: str, enabled: bool = True, weight: float = 1.0) -> dict:
    if kind not in ("rss", "hn"):
        raise DomainError(f"非法来源类型: {kind}", code="invalid_source_kind", status_code=422)
    duplicated = session.execute(select(NewsSource).where(NewsSource.name == name)).scalar_one_or_none()
    if duplicated is not None:
        raise DomainError(f"来源已存在: {name}", code="source_exists", status_code=409)
    source = NewsSource(name=name, kind=kind, endpoint=endpoint, enabled=1 if enabled else 0, weight=weight)
    session.add(source)
    session.commit()
    session.refresh(source)
    return source_to_dict(source)


def update_source(session: Session, source_id: int, fields: dict) -> dict:
    source = session.get(NewsSource, source_id)
    if source is None:
        raise NotFoundError(f"资讯来源不存在: {source_id}")
    if "name" in fields and fields["name"] is not None:
        source.name = fields["name"]
    if "endpoint" in fields and fields["endpoint"] is not None:
        source.endpoint = fields["endpoint"]
    if "enabled" in fields and fields["enabled"] is not None:
        source.enabled = 1 if fields["enabled"] else 0
    if "weight" in fields and fields["weight"] is not None:
        source.weight = float(fields["weight"])
    session.commit()
    session.refresh(source)
    return source_to_dict(source)


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


def list_items(
    session: Session,
    *,
    page: int = 1,
    page_size: int = 30,
    topic: str | None = None,
    source: str | None = None,
    sort: str = "latest",  # latest | top
    since: str | None = None,
    until: str | None = None,
    favorite: bool | None = None,
    unread: bool | None = None,
) -> dict:
    statement = select(NewsItem)
    if topic:
        statement = statement.where(NewsItem.topic == topic)
    if source:
        statement = statement.where(NewsItem.source == source)
    if favorite is not None:
        statement = statement.where(NewsItem.is_favorite == (1 if favorite else 0))
    if unread is not None:
        statement = statement.where(NewsItem.is_read == (0 if unread else 1))
    if since:
        statement = statement.where(NewsItem.published_at >= _to_utc_iso(since))
    if until:
        statement = statement.where(NewsItem.published_at <= _to_utc_iso(until, end_of_day=True))

    total = session.execute(select(func.count()).select_from(statement.subquery())).scalar_one()
    if sort == "top":
        statement = statement.order_by(NewsItem.score.desc(), NewsItem.published_at.desc())
    else:
        statement = statement.order_by(NewsItem.published_at.desc())
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    rows = session.execute(statement.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {
        "items": [item_to_dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _to_utc_iso(date_str: str, end_of_day: bool = False) -> str:
    """YYYY-MM-DD → UTC ISO 起点/终点；带时间的 ISO 原样转 UTC。"""

    from datetime import time as dt_time

    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
        moment = datetime.combine(day, dt_time.max if end_of_day else dt_time.min)
        return moment.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        parsed = datetime.fromisoformat(date_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def get_item(session: Session, item_id: int) -> NewsItem:
    item = session.get(NewsItem, item_id)
    if item is None:
        raise NotFoundError(f"资讯不存在: {item_id}")
    return item


def update_item(session: Session, item_id: int, fields: dict) -> dict:
    item = get_item(session, item_id)
    if "is_favorite" in fields and fields["is_favorite"] is not None:
        item.is_favorite = 1 if fields["is_favorite"] else 0
    if "is_read" in fields and fields["is_read"] is not None:
        item.is_read = 1 if fields["is_read"] else 0
    session.commit()
    session.refresh(item)
    return item_to_dict(item)


# ---------- 过期（仅判定，供阶段 5；本阶段禁止任何删除） ----------

def expired_items(session: Session, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(tz=timezone.utc)
    rows = session.execute(select(NewsItem).where(NewsItem.is_favorite == 0)).scalars().all()
    return [item_to_dict(row) for row in rows if is_expired(datetime.fromisoformat(row.published_at), now)]
