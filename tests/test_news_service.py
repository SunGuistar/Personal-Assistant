"""资讯 service 单元测试（隔离临时库）：种子/去重/榜单排名。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

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
    assert len(session.execute(select(NewsItem)).scalars().all()) == 1


def test_upsert_dedup_by_title_hash_across_sources(session):
    hn = _source(session, name="HN", kind="hn")
    rss = _source(session)
    news_service.upsert_items(session, hn, [_raw(title="Same Title", url="https://a.com/1")])
    news_service.upsert_items(session, rss, [_raw(title="same  title", url="https://b.com/2")])
    assert len(session.execute(select(NewsItem)).scalars().all()) == 1


def test_upsert_scores_with_source_weight(session):
    hn = _source(session, name="HN", kind="hn")
    news_service.upsert_items(session, hn, [_raw(points=400)])  # norm_heat = 400/500 = 0.8
    item = session.execute(select(NewsItem)).scalar_one()
    assert item.norm_heat == 0.8
    assert 0 < item.score <= 0.8 * 1.5
    assert item.topic == "python"


def test_top_items_ranking_from_cache(session):
    sources = [_source(session, name=f"Src{i}") for i in range(3)]
    for src in sources:
        news_service.upsert_items(
            session,
            src,
            [
                _raw(title=f"{src.name} Python tip {i}", url=f"https://{src.name}.example/t{i}", hours_old=i + 1, points=10 * i)
                for i in range(4)
            ],
        )
    result = news_service.top_items(session, limit=10)
    assert result["total"] == 10  # 3 源 × 4 条，单源上限 4 不截断多样性
    assert [item["rank"] for item in result["items"]] == list(range(1, 11))
    # 确定性：再次查询排名一致
    assert result["items"] == news_service.top_items(session, limit=10)["items"]
    first_url = result["items"][0]["url"]
    assert all(item["url"] != first_url for item in result["items"][1:])  # 无重复


def test_top_items_source_cap(session):
    only = _source(session)
    news_service.upsert_items(
        session,
        only,
        [_raw(title=f"tip {i}", url=f"https://only.example/t{i}", hours_old=1, points=50) for i in range(8)],
    )
    result = news_service.top_items(session, limit=10)
    assert result["total"] == 4  # 单来源上榜上限 DEFAULT_SOURCE_CAP


def test_top_items_actual_count_when_few(session):
    rss = _source(session)
    news_service.upsert_items(session, rss, [_raw(hours_old=1)])
    result = news_service.top_items(session, limit=10)
    assert result["total"] == 1  # 不足 10 条按实际数量
