"""资讯 service 单元测试（隔离临时库）：种子/去重/状态保留/过期。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config

from app.adapters.news_common import RawNewsItem
from app.models import NewsItem, NewsSource
from app.services import news_service

NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def session(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'news.db'}"
    import os
    from pathlib import Path

    os.environ["PH_DATABASE_URL"] = db_url
    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        yield s
    engine.dispose()


def _source(session, name="Test RSS", kind="rss"):
    source = NewsSource(name=name, kind=kind, endpoint="https://example.com/feed", enabled=1, weight=1.5)
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def _raw(title="Hello Python World", url="https://example.com/a", hours_old=1, points=0.0):
    return RawNewsItem(
        title=title,
        url=url,
        published_at=NOW - timedelta(hours=hours_old),
        raw_summary="summary",
        heat_raw=points,
    )


def test_seed_default_sources_idempotent(session):
    news_service.ensure_default_sources(session)
    first = session.execute(select(NewsSource)).scalars().all()
    news_service.ensure_default_sources(session)  # 再次执行不重复
    second = session.execute(select(NewsSource)).scalars().all()
    assert len(first) == len(news_service.DEFAULT_SOURCES)
    assert len(second) == len(first)


def test_upsert_dedup_by_normalized_url(session):
    source = _source(session)
    news_service.upsert_items(session, source, [_raw(url="https://example.com/a/?utm_source=x")])
    news_service.upsert_items(session, source, [_raw(url="https://EXAMPLE.com/a")])  # 规范化后同 URL
    assert session.execute(select(NewsItem)).scalars().all().__len__() == 1


def test_upsert_dedup_by_title_hash_across_sources(session):
    hn = _source(session, name="HN", kind="hn")
    rss = _source(session)
    news_service.upsert_items(session, hn, [_raw(title="Same Title", url="https://a.com/1")])
    news_service.upsert_items(session, rss, [_raw(title="same  title", url="https://b.com/2")])
    assert session.execute(select(NewsItem)).scalars().all().__len__() == 1


def test_refetch_preserves_favorite_and_read(session):
    source = _source(session)
    news_service.upsert_items(session, source, [_raw()])
    item = session.execute(select(NewsItem)).scalar_one()
    news_service.update_item(session, item.id, {"is_favorite": True, "is_read": True})

    news_service.upsert_items(session, source, [_raw()])  # 重复抓取同批数据
    after = session.execute(select(NewsItem)).scalar_one()
    assert after.id == item.id
    assert after.is_favorite == 1 and after.is_read == 1  # 状态不被重置


def test_upsert_scores_with_source_weight(session):
    hn = _source(session, name="HN", kind="hn")
    news_service.upsert_items(session, hn, [_raw(points=400)])  # norm_heat = 400/500 = 0.8
    item = session.execute(select(NewsItem)).scalar_one()
    assert item.norm_heat == 0.8
    assert 0 < item.score <= 0.8 * 1.5
    assert item.topic == "python"


def test_expired_items_favorite_exempt(session):
    source = _source(session)
    news_service.upsert_items(
        session,
        source,
        [_raw(title="Old item A", url="https://example.com/old", hours_old=24 * 8)],
    )
    news_service.upsert_items(
        session,
        source,
        [_raw(title="Old item B", url="https://example.com/old2", hours_old=24 * 8)],
    )
    kept = session.execute(select(NewsItem).where(NewsItem.title == "Old item B")).scalar_one()
    news_service.update_item(session, kept.id, {"is_favorite": True})

    expired = news_service.expired_items(session, now=NOW)
    assert [row["title"] for row in expired] == ["Old item A"]


def test_list_items_filter_sort(session):
    source = _source(session)
    news_service.upsert_items(
        session,
        source,
        [
            _raw(title="Python news", url="https://example.com/p1", hours_old=1),
            _raw(title="Agent news", url="https://example.com/p2", hours_old=3),
        ],
    )
    latest = news_service.list_items(session, sort="latest")
    assert latest["total"] == 2
    assert "Python news" == latest["items"][0]["title"]
    filtered = news_service.list_items(session, topic="agent")
    assert filtered["total"] == 1 and filtered["items"][0]["title"] == "Agent news"
    since = news_service.list_items(session, since=(NOW - timedelta(hours=2)).isoformat())
    assert since["total"] == 1
