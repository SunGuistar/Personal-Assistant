"""热榜/精选策略：假 HTTP、临时库，禁止真实模型与网络。"""
import json

import pytest
import respx
from sqlalchemy import select

from app.morning_report.adapters import NewsCandidate, chinanews, sina_hot, remoshuang
from app.morning_report.adapters.article import parse_article
from app.morning_report.adapters.http_common import FetchError
from app.morning_report.graph.workflow import _limit_selection
from app.morning_report.models import NewsItem, RunRecord
from app.morning_report.services import news_pipeline


def hot_row(**extra):
    return {"title": "国际局势最新进展", "url": "https://news.sina.com.cn/w/test.shtml",
            "media": "央视", "time": "Tue, 10 Nov 2026 12:02:00 +0800",
            "top_time": "20261111", "top_num": "12,345", **extra}


def test_hot_js_wrapper_and_real_dates():
    rows = sina_hot.parse_hot("var news_ = " + json.dumps({"data": [hot_row(top_time="20261110")]}),
                              "international", "2026-11-11", "2026-11-11T08:00:00+08:00")
    item = rows[0]
    assert item.raw["rank"] == 1 and item.raw["rank_value"] == 12345
    assert item.raw["rank_date"] == "2026-11-10" and item.raw["stale_rank"] is True
    assert item.published_at == "2026-11-10T12:02:00+08:00"


@pytest.mark.parametrize("date", ["20261109", "20261112", "wrong", None])
def test_hot_rejects_stale_future_or_unknown_date(date):
    with pytest.raises(FetchError):
        sina_hot.parse_hot(json.dumps({"data": [hot_row(top_time=date)]}),
                           "domestic", "2026-11-11", "now")


def test_hot_limits_twenty_and_does_not_invent_article_time():
    data = [hot_row(time=None) for _ in range(25)]
    rows = sina_hot.parse_hot(json.dumps({"data": data}), "domestic", "2026-11-11", "now")
    assert len(rows) == 20 and rows[-1].raw["rank"] == 20
    assert all(row.published_at is None for row in rows)


@pytest.mark.parametrize("body", ["<html>unavailable</html>", '{"data": []}', '{"other": []}'])
def test_hot_empty_or_changed_format_is_failure(body):
    with pytest.raises(FetchError):
        sina_hot.parse_hot(body, "domestic", "2026-11-11", "now")


def test_article_uses_visible_time_and_excludes_script():
    body = "这是一篇有完整上下文的新闻正文。" * 5
    result = parse_article('<script>2099-01-01 00:00:00</script>'
                           '<div>2026年11月10日 12:02 来源：中新网</div><p>' + body + '</p>')
    assert result["published_at"] == "2026-11-10T12:02:00+08:00"
    assert body in result["summary"] and "2099" not in result["summary"]
    assert parse_article('<meta name="publishdate" content="2026-11-10">')["published_at"] is None


def test_featured_limits_and_fetches_detail_not_archive():
    html = ''.join(f'<a href="/gn/2026/11-10/{10000000 + i}.shtml">政策新闻{i}</a>' for i in range(20))
    with respx.mock(assert_all_called=False) as mock:
        for page in chinanews.FEATURED_PAGES:
            mock.get(page).respond(200, text=html)
        detail_routes = [mock.get(f"https://www.chinanews.com.cn/gn/2026/11-10/{10000000+i}.shtml").respond(
            200, text='<time datetime="2026-11-10T10:00:00+08:00"></time><p>' + '新闻正文' * 20 + '</p>') for i in range(20)]
        rows = chinanews.fetch_featured("2026-11-10T08:00:00+08:00", "2026-11-11T08:00:00+08:00")
    assert len(rows) == 5
    assert all(row.raw["selection_kind"] == "featured" and row.summary for row in rows)
    assert sum(route.call_count for route in detail_routes) == 5


def test_final_selection_is_limited_and_deduplicated():
    news = [{"id": i, "category": "domestic", "event_group_id": i // 2} for i in range(2, 32)]
    choice = {"domestic": [{"id": i} for i in range(2, 32)] + [{"id": 1000}], "international": []}
    result = _limit_selection(choice, news)
    assert len(result["domestic"]) == 10
    assert [item["id"] for item in result["domestic"]] == list(range(2, 22, 2))


def test_rank_failure_has_no_fallback_and_keeps_history(fclient, monkeypatch):
    def fail(*args):
        raise FetchError("test://hot", "unavailable")
    monkeypatch.setattr(chinanews, "fetch_hot_ranked", lambda *a, **k: fail())
    monkeypatch.setattr(news_pipeline.aihot, "fetch_daily", lambda report_date: [])
    monkeypatch.setattr(remoshuang, "fetch_daily", lambda day: [])
    monkeypatch.setattr(chinanews, "fetch_featured", lambda *args, **kwargs: [NewsCandidate(
        category="domestic", title="重要政策公布", summary="可靠的新闻摘要", source_name="中国新闻网",
        source_url="https://www.chinanews.com.cn/gn/2026/11-10/10000000.shtml",
        published_at="2026-11-10T10:00:00+08:00", adapter="chinanews", raw={"selection_kind": "featured"})])
    with fclient.app.state.mr_session_factory() as mr:
        old = news_pipeline.create_collect_run(mr, "2026-11-10")
        mr.add(NewsItem(run_id=old.id, category="domestic", title="历史新闻", source_url="old", content_hash="old"))
        mr.commit()
        current = news_pipeline.create_collect_run(mr, "2026-11-11")
        summary = news_pipeline.run_collect(mr, current.id)
        assert set(summary["source_failures"]) == {"chinanews_domestic", "chinanews_international"}
        assert mr.get(RunRecord, current.id).status == "degraded"
        assert summary["saved_unique"] == 0  # 不通过精选/其他来源回填
        assert news_pipeline.collection_is_current(mr, current.id)
        assert not news_pipeline.collection_is_current(mr, old.id)
        assert mr.execute(select(NewsItem).where(NewsItem.run_id == old.id)).scalar_one().title == "历史新闻"


def test_event_merge_preserves_related_sources():
    first = NewsCandidate("domestic", "重要政策公布", "摘要", "央视", "https://news.sina.com.cn/test", "2026-11-10T10:00:00+08:00", "sina_hot", {"selection_kind": "hot", "rank": 1})
    second = NewsCandidate("domestic", "重要政策公布", "摘要", "中国新闻网", "https://www.chinanews.com.cn/test", first.published_at, "chinanews", {"selection_kind": "featured"})
    rows, merged = news_pipeline._merge_candidates([first, second])
    assert len(rows) == 1 and merged == 1
    assert rows[0].raw["related_sources"][0]["source_name"] == "中国新闻网"


def test_time_window_uses_timezone_and_exclusive_end():
    start, end = "2026-11-10T08:00:00+08:00", "2026-11-11T08:00:00+08:00"
    assert news_pipeline._in_window("2026-11-10T00:00:00Z", start, end)
    assert not news_pipeline._in_window("2026-11-11T00:00:00Z", start, end)
    assert not news_pipeline._in_window(None, start, end)
    assert not news_pipeline._in_window("2026-11-10T10:00:00", start, end)


def test_rank_change_invalidates_analysis_cache(fclient):
    import asyncio
    from tests.test_morning_stage4_graph import FakeLLM, _deps, _initial, _run_graph

    llm = FakeLLM()
    first = _initial(run_id=1)
    first["news"] = [{**item, "rank": 1} for item in first["news"]]
    asyncio.run(_run_graph(fclient, _deps(fclient, llm=llm, run_id=1), first))
    second = _initial(run_id=2)
    second["news"] = [{**item, "rank": 2} for item in second["news"]]
    asyncio.run(_run_graph(fclient, _deps(fclient, llm=llm, run_id=2), second))
    assert sum("选出值得进入晨报" in call for call in llm.calls) == 0
    assert len(llm.calls) == 0  # 主编程序组装，不调用普通模型


def test_morning_isolation_blocks_unmocked_http_and_uses_memory_store():
    import httpx
    from app.morning_report.services import report_service

    with pytest.raises(AssertionError):
        httpx.get("https://must-not-contact.invalid/", timeout=1)
    store = report_service.QdrantStore("http://127.0.0.1:6333")
    assert type(store.client._client).__name__ == "QdrantLocal"
    provider = report_service.DefaultEmbeddingProvider()
    assert provider.model_name == "fake-morning-isolated"


def test_fetch_text_respects_html_declared_gb2312():
    from app.morning_report.adapters.http_common import fetch_text
    html = '<meta charset="gb2312"><div>热点排行 国内新闻</div>'
    with respx.mock() as mock:
        mock.get("https://www.chinanews.com.cn/china/").respond(
            200, content=html.encode("gb18030"), headers={"content-type": "text/html"})
        assert fetch_text("https://www.chinanews.com.cn/china/") == html


def test_outdated_official_ranking_candidates_reach_pipeline_for_diagnostics(monkeypatch):
    from app.morning_report.adapters import article
    html = '<div class="hotlist"><a href="/gn/2026/11-09/10728638.shtml">旧榜标题</a></div>'
    monkeypatch.setattr(chinanews, "fetch_text", lambda url: html)
    monkeypatch.setattr(article, "fetch_article", lambda url: {
        "published_at": "2026-11-09T10:00:00+08:00", "summary": "摘要"})
    rows = chinanews.fetch_hot_ranked("domestic", "2026-11-10T08:00:00+08:00", "2026-11-11T08:00:00+08:00")
    assert len(rows) == 1
    assert rows[0].published_at == "2026-11-09T10:00:00+08:00"


@pytest.mark.parametrize("stamp", ["2026-11-09T10:00:00+08:00", "2026-11-11T12:00:00+08:00", None])
def test_official_ranking_kept_without_time_filter(fclient, monkeypatch, stamp):
    monkeypatch.setattr(news_pipeline.aihot, "fetch_daily", lambda day: [])
    monkeypatch.setattr(chinanews, "fetch_hot_ranked", lambda cat, *a, **kw: [NewsCandidate(
        cat, "榜单新闻", "摘要", "中国新闻网", f"https://example.com/{cat}",
        stamp, "chinanews", {"selection_kind": "official_hotlist", "rank": 1})])
    with fclient.app.state.mr_session_factory() as mr:
        run = news_pipeline.create_collect_run(mr, "2026-11-11")
        summary = news_pipeline.run_collect(mr, run.id)
        assert summary["saved_unique"] == 2
        assert summary["out_of_window_dropped"] == 0
        assert summary["clue_only"] == 0
        assert summary["by_category"] == {"domestic": 1, "international": 1, "ai": 0}
        assert all("已排除" not in note and "仅保留为线索" not in note for note in summary["coverage_notes"])
        assert [r.published_at for r in mr.execute(select(NewsItem)).scalars()] == [stamp, stamp]


@pytest.mark.parametrize("stamp", ["2026-11-09T10:00:00+08:00", "2026-11-11T12:00:00+08:00", None])
def test_generation_snapshot_keeps_news_regardless_of_time(fclient, monkeypatch, stamp):
    from app.morning_report.services import report_service
    from app.morning_report.config import MRSettings
    from tests.test_morning_stage4_graph import _deps
    captured = {}
    class SnapshotCaptured(Exception):
        pass
    async def execute(deps, initial, run_id):
        captured.update(initial)
        raise SnapshotCaptured()
    monkeypatch.setattr(report_service, "_execute", execute)
    with fclient.app.state.mr_session_factory() as mr:
        collect = news_pipeline.create_collect_run(mr, "2026-11-11")
        collect.status = "success"
        for cat in ("domestic", "international"):
            mr.add(NewsItem(run_id=collect.id, category=cat, title=cat, source_url=cat,
                           published_at=stamp, content_hash=cat))
        mr.add(NewsItem(run_id=collect.id, category="ai", title="AI complete", source_url="https://example.com/ai",
                        content_hash="ai-complete", raw_ref={"daily_member": True, "daily_date": "2026-11-11"}))
        run = RunRecord(run_date="2026-11-11", kind="generate", status="pending")
        mr.add(run); mr.commit()
        with pytest.raises(SnapshotCaptured):
            report_service.run_generate(mr, run.id, MRSettings(schedule_enabled=False), mode="manual",
                deps_override=_deps(fclient, run_id=run.id),
                mr_session_factory=fclient.app.state.mr_session_factory)
    assert {n["category"] for n in captured["news"]} == {"domestic", "international"}
    assert captured["clues"] == []
