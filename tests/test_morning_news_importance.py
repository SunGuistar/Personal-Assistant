"""新闻星标 API、独立库升级及重新采集继承；全程隔离临时数据库。"""
from sqlalchemy import text, select
from app.morning_report import db
from app.morning_report.models import NewsItem, ReportVersion
from app.morning_report.services import news_pipeline
from app.morning_report.adapters import NewsCandidate


def test_upgrade_old_database_preserves_news_and_defaults(tmp_path):
    engine = db.make_engine(tmp_path / "old.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE news_items (id INTEGER PRIMARY KEY, title TEXT)"))
        conn.execute(text("INSERT INTO news_items VALUES (1, 'old news')"))
        conn.execute(text("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)"))
        for version in (1, 2, 3):
            conn.execute(text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": version})
    assert db.run_migrations(engine) == [4, 5]
    assert db.run_migrations(engine) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title, is_important FROM news_items")).one() == ("old news", 0)
        assert conn.execute(text("SELECT COUNT(*) FROM news_favorite_settings")).scalar_one() == 0
    engine.dispose()


def test_mark_unmark_persist_and_duplicate_sync(fclient):
    sf = fclient.app.state.mr_session_factory
    with sf() as mr:
        first = NewsItem(run_id=1, category="ai", title="news", source_url="https://example.com/news", content_hash="same")
        duplicate = NewsItem(run_id=2, category="ai", title="news", source_url="https://example.com/news", content_hash="same")
        unrelated = NewsItem(run_id=1, category="ai", title="other", content_hash="other")
        mr.add_all([first, duplicate, unrelated]); mr.flush()
        version = ReportVersion(report_date="2026-11-11", content_md="test", sections={"news_selection": {"ai": [{"id": first.id}]}})
        mr.add(version); mr.commit()
        news_id, duplicate_id, other_id, version_id = first.id, duplicate.id, unrelated.id, version.id
    url = f"/api/morning/news/{news_id}/importance"
    assert fclient.get(f"/api/morning/report/{version_id}/news").json()["items"][0]["is_important"] is False
    for value in (True, True, False):
        response = fclient.patch(url, json={"is_important": value})
        assert response.status_code == 200 and response.json()["is_important"] is value
        with sf() as mr:
            assert mr.get(NewsItem, news_id).is_important is value
            assert mr.get(NewsItem, duplicate_id).is_important is value
            assert mr.get(NewsItem, other_id).is_important is False
    assert fclient.patch(url, json={"is_important": "false"}).status_code == 422
    assert fclient.patch("/api/morning/news/999999/importance", json={"is_important": True}).status_code == 404
    assert fclient.get("/api/morning/report/999999/news").status_code == 404


def test_recollection_inherits_importance(fclient, monkeypatch):
    from app.morning_report.adapters import aihot, chinanews
    url, title = "https://example.com/news", "AI News"
    monkeypatch.setattr(aihot, "fetch_daily", lambda day: [NewsCandidate("ai", title, "summary", "AIHOT", url, None,
        "aihot", {"daily_member": True, "daily_date": day})])
    monkeypatch.setattr(chinanews, "fetch_hot_ranked", lambda *a, **kw: [])
    with fclient.app.state.mr_session_factory() as mr:
        old = NewsItem(run_id=999, category="ai", title=title, source_url=url,
                       content_hash=news_pipeline.content_hash(title, url), is_important=True)
        mr.add(old); mr.commit()
        run = news_pipeline.create_collect_run(mr, "2026-11-11")
        news_pipeline.run_collect(mr, run.id)
        item = mr.execute(select(NewsItem).where(NewsItem.run_id == run.id)).scalar_one()
        assert item.is_important is True
