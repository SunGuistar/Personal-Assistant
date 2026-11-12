"""08:30 调度与来源缺失降级；隔离库、假模型，不发真实请求。"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.morning_report.config import MRSettings
from app.morning_report.models import ReportVersion, RunRecord, RunStage
from app.morning_report.adapters import aihot, chinanews, NewsCandidate
from app.morning_report.adapters.http_common import FetchError
from app.morning_report.services import news_pipeline, report_service, progress
from app.morning_report.services.scheduler import create_scheduler
from app.morning_report.services.llm_router import is_allowed_period
from tests.test_morning_stage4_graph import _deps


def test_default_scheduler_is_0830_without_changing_content_window(monkeypatch):
    monkeypatch.delenv("PH_MR_SCHEDULE_HOUR", raising=False)
    monkeypatch.delenv("PH_MR_SCHEDULE_MINUTE", raising=False)
    settings = MRSettings()
    scheduler, _ = create_scheduler(settings, None, None, None)
    cst = timezone(timedelta(hours=8))
    fire = scheduler.get_jobs()[0].trigger.get_next_fire_time(None, datetime(2026, 11, 12, 8, 0, tzinfo=cst))
    assert (fire.hour, fire.minute) == (8, 30)
    assert is_allowed_period(fire)[0] is True


@pytest.mark.parametrize("all_missing,reuse", [(True, False), (False, False), (False, True)])
def test_missing_news_publishes_personal_report_with_specific_errors(fclient, monkeypatch, all_missing, reuse):
    reason = "日报日期不符：期望 2026-11-12，实际 2026-11-11"
    def fail_ai(day): raise FetchError("test://ai", reason)
    def cn(category, *a, **kw):
        if all_missing: raise FetchError("test://cn", "HTTP 503")
        return [NewsCandidate(category, category + " headline", "summary", "中新网", f"https://example.com/{category}",
            None, "chinanews", {"rank": 1})]
    monkeypatch.setattr(aihot, "fetch_daily", fail_ai)
    monkeypatch.setattr(chinanews, "fetch_hot_ranked", cn)
    sf = fclient.app.state.mr_session_factory
    with sf() as mr:
        if reuse:
            collect = news_pipeline.create_collect_run(mr, "2026-11-12")
            news_pipeline.run_collect(mr, collect.id)
        run = RunRecord(run_date="2026-11-12", kind="generate", status="pending")
        mr.add(run); mr.commit(); rid = run.id
        result = report_service.run_generate(mr, rid, MRSettings(schedule_enabled=False), mode="manual",
            deps_override=_deps(fclient, run_id=rid), mr_session_factory=sf,
            personal_ctx_override={"daily_done": [{"source_id": "daily_tasks:1", "title": "完成事项"}], "source_meta": {"status": "ok"}})
    assert result["status"] == "degraded"
    with sf() as mr:
        report = mr.execute(select(ReportVersion).where(ReportVersion.run_id == rid)).scalar_one()
        ai = report.content_md.split("### AI", 1)[1].split("## 三、", 1)[0]
        assert reason in ai and "AIHOT获取失败" in ai
        assert "## 三、我的昨日" in report.content_md and "## 四、今日建议" in report.content_md
        if all_missing:
            assert "中新网国内获取失败：HTTP 503" in report.content_md
            assert "中新网国际获取失败：HTTP 503" in report.content_md
        stages = {row.stage: row for row in mr.execute(select(RunStage).where(RunStage.run_id == rid)).scalars()}
        assert stages["collect"].status == "warning" and stages["info_analysis"].status == "warning"
        assert stages["publish"].status == "success"
        snap = progress.snapshot(mr, rid)
        assert snap["done_count"] == snap["total_count"] == 8
