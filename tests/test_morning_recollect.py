"""资讯完整性决定补采，生成模式只决定原有阶段缓存行为。"""
import pytest
from sqlalchemy import select
from app.morning_report.config import MRSettings
from app.morning_report.models import NewsItem, RunLog, RunRecord, StageCache
from app.morning_report.services import news_pipeline, report_service, stage_cache
from tests.test_morning_stage4_graph import _deps


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("case", ["complete", "missing_ai", "source_failed"])
def test_both_modes_recollect_only_if_news_incomplete(fclient, monkeypatch, full, case):
    sf = fclient.app.state.mr_session_factory
    calls = []
    def seed(mr, run_id, categories):
        for category in categories:
            mr.add(NewsItem(run_id=run_id, category=category, title=category, source_url=f"https://example.com/{category}",
                content_hash=category, raw_ref={"daily_member": category == "ai", "daily_date": "2026-11-12"}))
    with sf() as mr:
        old = news_pipeline.create_collect_run(mr, "2026-11-12")
        old.status = "degraded"
        seed(mr, old.id, ["domestic", "international"] + ([] if case == "missing_ai" else ["ai"]))
        mr.add(RunLog(run_id=old.id, stage="collect", message="采集完成", detail={
            "source_failures": {"aihot": "HTTP 503"} if case == "source_failed" else {}}))
        run = RunRecord(run_date="2026-11-12", kind="generate", status="pending")
        mr.add(run); mr.commit(); rid, old_id = run.id, old.id
        stage_cache.put_cache(mr, "sample", "key", {"keep": True})
    def collect(mr, run_id, **kwargs):
        calls.append(run_id)
        seed(mr, run_id, ["domestic", "international", "ai"])
        mr.get(RunRecord, run_id).status = "success"
        mr.commit()
        return {}
    class Captured(Exception): pass
    async def execute(deps, initial, run_id): raise Captured()
    monkeypatch.setattr(news_pipeline, "run_collect", collect)
    monkeypatch.setattr(news_pipeline, "collection_is_current", lambda *a: True)
    monkeypatch.setattr(report_service, "_execute", execute)
    with sf() as mr:
        with pytest.raises(Captured):
            report_service.run_generate(mr, rid, MRSettings(schedule_enabled=False), mode="manual", clear_cache=full,
                deps_override=_deps(fclient, run_id=rid), mr_session_factory=sf)
        assert bool(calls) is (case != "complete")
        if calls: assert calls[0] != old_id
        assert (mr.execute(select(StageCache)).first() is None) is full
        assert mr.execute(select(NewsItem).where(NewsItem.run_id == old_id)).first() is not None
