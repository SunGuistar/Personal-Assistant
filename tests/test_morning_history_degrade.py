"""生成不再检查或更新历史索引；无真实网络/模型/数据库。"""
import pytest
from sqlalchemy import select
from app.morning_report.config import MRSettings
from app.morning_report.models import NewsItem, ReportVersion, RunRecord, RunStage
from app.morning_report.services import report_service, news_pipeline, llm_router
from tests.test_morning_stage4_graph import FakeLLM, TraceSubagents, NEWS


@pytest.mark.parametrize("failure", [None, "dirty", "offline", "initialization"])
def test_generation_never_uses_history_or_news_indexes(fclient, monkeypatch, failure):
    sf = fclient.app.state.mr_session_factory
    settings = MRSettings(schedule_enabled=False)
    with sf() as mr:
        collect = news_pipeline.create_collect_run(mr, "2026-11-10")
        collect.status = "success"
        for item in NEWS:
            mr.add(NewsItem(run_id=collect.id, category=item["category"], title=item["title"],
                summary=item["summary"], source_url=item["source_url"], content_hash=item["content_hash"]))
        run = RunRecord(run_date="2026-11-10", kind="generate", status="pending")
        mr.add(run); mr.commit(); rid = run.id
    monkeypatch.setattr(news_pipeline, "collection_is_current", lambda *a: True)
    from app.morning_report.services import index_sync
    def forbidden(*a, **kw):
        pytest.fail("generation must not initialize, check or write any vector index")
    monkeypatch.setattr(report_service, "QdrantStore", forbidden)
    monkeypatch.setattr(report_service, "DefaultEmbeddingProvider", forbidden)
    monkeypatch.setattr(index_sync, "check_required_indexes", forbidden)
    monkeypatch.setattr(index_sync, "sync_tech_news", forbidden)
    monkeypatch.setattr(index_sync, "sync_report_version", forbidden)
    agents = []
    class Agents(TraceSubagents):
        def __init__(self, settings):
            super().__init__(); agents.append(self)
        def configure_context(self, *a): pass
    monkeypatch.setattr(report_service, "LangChainSubagentRunner", Agents)
    monkeypatch.setattr(llm_router, "dev_client", forbidden)
    monkeypatch.setattr(llm_router, "ChatClient", forbidden)
    with sf() as mr:
        result = report_service.run_generate(mr, rid, settings, mode="manual", mr_session_factory=sf,
            personal_ctx_override={"daily_done": [], "source_meta": {"status": "ok"}})
    assert result["status"] in ("success", "degraded")
    assert agents
    with sf() as mr:
        version = mr.execute(select(ReportVersion).where(ReportVersion.run_id == rid)).scalar_one()
        stages = {stage.stage: stage for stage in mr.execute(select(RunStage).where(RunStage.run_id == rid)).scalars()}
        assert stages["snapshot"].title == "准备本轮数据"
        assert stages["snapshot"].status == "success" and version.snapshot_id
        assert "index" not in stages
        assert "历史晨报检索不可用" not in version.content_md
        assert result["status"] == "success"
