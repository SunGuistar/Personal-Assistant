"""新闻结构化展示契约；历史报告只读补齐，新报告保存快照。"""
from sqlalchemy import select
from app.morning_report.models import NewsItem, ReportVersion
from app.morning_report.services.report_news_content import build_news_content
from app.morning_report.graph.workflow import node_publish
from tests.test_morning_stage4_graph import _deps, _initial


def test_snapshot_keeps_selection_order_and_builds_overview_and_errors():
    sources = [{"id": 1, "title": "国内首条", "source_url": "https://example.com/d", "summary": "国内摘要"},
               {"id": 2, "title": "AI首条", "url": "https://example.com/ai", "summary": "AI摘要", "section_label": "模型发布/更新"},
               {"id": 3, "title": "技巧", "url": "https://example.com/tip", "summary": "技巧摘要", "section_label": "技巧与观点"}]
    result = build_news_content({"domestic": [{"id": 1}], "international": [], "ai": [{"id": 2}, {"id": 3}]}, sources,
                                {"international": "来源 HTTP 503"})
    assert result["version"] == 1
    assert [item["id"] for item in result["categories"]["ai"]] == [2, 3]
    assert [item["display_type"] for item in result["overview"]] == ["国内新闻", "AI新闻", "技巧与观点"]
    assert result["categories"]["ai"][1]["summary"] == "技巧摘要"
    assert result["errors"] == {"international": "来源 HTTP 503"}


def test_legacy_report_hydration_does_not_rewrite_database(fclient):
    sf = fclient.app.state.mr_session_factory
    original = "## 二、重要资讯\n### AI 前沿\n未经核验的模型引语\n- [错误标题](https://example.com/wrong)"
    with sf() as mr:
        item = NewsItem(run_id=1, category="ai", title="原始新闻标题", source_url="https://example.com/right",
                        summary="原始摘要", raw_ref={"section_label": "模型发布/更新"})
        mr.add(item); mr.flush()
        report = ReportVersion(report_date="2026-11-12", content_md=original,
                               sections={"news_selection": {"ai": [{"id": item.id}]}})
        mr.add(report); mr.commit(); vid, nid = report.id, item.id
    body = fclient.get("/api/morning/report", params={"report_date": "2026-11-12"}).json()
    snapshot = body["sections"]["news_content"]
    assert snapshot["categories"]["ai"][0] == {"id": nid, "category": "ai", "title": "原始新闻标题",
        "url": "https://example.com/right", "summary": "原始摘要", "section_label": "模型发布/更新", "published_at": None}
    assert body["content_md"] == original
    with sf() as mr:
        stored = mr.get(ReportVersion, vid)
        assert "news_content" not in stored.sections
        assert stored.content_md == original


def test_publish_stores_news_content_separately_from_markdown(fclient):
    state = _initial()
    state.update(news_selection={"domestic": [{"id": 1}], "international": [{"id": 2}], "ai": state["ai_daily"]},
        goal_result={}, advice_result={}, draft="### AI 前沿\n模型任意标题", news_errors={})
    result = node_publish(state, _deps(fclient))
    with fclient.app.state.mr_session_factory() as mr:
        report = mr.get(ReportVersion, result["publish"]["version_id"])
        assert report.sections["news_content"]["categories"]["ai"][0]["title"] == state["ai_daily"][0]["title"]
        assert report.sections["news_content"]["categories"]["domestic"][0]["summary"] == state["news"][0]["summary"]
        assert report.content_md == state["draft"]
