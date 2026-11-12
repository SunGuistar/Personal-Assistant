"""重新组装只使用已发布输入，所有测试使用隔离数据库。"""
from sqlalchemy import select
from app.morning_report.models import ReportVersion, RunRecord, TokenUsage, RunStage
from app.morning_report.services.report_actions import run_reassemble


def seed(mr):
    run = RunRecord(run_date="2026-11-10", kind="generate", status="success")
    mr.add(run)
    mr.flush()
    yesterday = {"version": 1, "completed": [{"id": "done", "title": "原有成果", "summary": "原有总结。", "detail": "", "kind": "confirmed", "evidence_ids": ["daily_tasks:1"]}], "goal_progress": [], "attention": [], "questions": [], "additional": [], "notices": []}
    report = ReportVersion(run_id=run.id, report_date=run.run_date, version_no=1, is_primary=True,
        status="published", content_md="旧排版", snapshot_id="original", window_start="2026-11-09T08:00:00+08:00", window_end="2026-11-10T08:00:00+08:00", sections={
        "news_selection": {"domestic": [], "international": [], "ai": []},
        "assembly_input": {"news": [], "ai_daily": [], "coverage_notes": ["原始采集说明"], "news_errors": {"ai": "原始缺失原因"}},
        "yesterday_content": yesterday, "goal": {"status": "ok", "analysis": {}},
        "advice": {"status": "ok", "advices": [{"content": "原有建议", "basis": "原有依据", "next_step": "原有下一步"}]}})
    mr.add(report)
    mr.commit()
    return report.id


def test_reassemble_reuses_saved_results_and_records_zero_tokens(fclient, monkeypatch):
    from app.morning_report.services import report_service, news_pipeline
    def forbidden(*args, **kwargs):
        raise AssertionError("must not generate or collect")
    monkeypatch.setattr(report_service, "run_generate", forbidden)
    monkeypatch.setattr(news_pipeline, "run_collect", forbidden)
    sf = fclient.app.state.mr_session_factory
    with sf() as mr:
        source_id = seed(mr)
        run = RunRecord(run_date="2026-11-10", kind="generate", status="pending")
        mr.add(run); mr.commit(); run_id = run.id
        result = run_reassemble(mr, run_id, source_id, mr_session_factory=sf)
        assert result["status"] == "success"
    with sf() as mr:
        source = mr.get(ReportVersion, source_id)
        output = mr.get(ReportVersion, result["publish"]["version_id"])
        assert source.content_md == "旧排版" and output.version_no == 2
        assert output.generation_mode == "reassemble" and output.snapshot_id == source.snapshot_id
        assert "原有成果" in output.content_md and "原有总结。" in output.content_md
        assert "原有建议" in output.content_md and "原始缺失原因" in output.content_md
        assert output.sections["yesterday_content"] == source.sections["yesterday_content"]
        assert output.sections["goal"] == source.sections["goal"]
        assert not mr.execute(select(TokenUsage).where(TokenUsage.run_id == run_id)).scalars().all()
        stages = {row.stage: row.status for row in mr.execute(select(RunStage).where(RunStage.run_id == run_id)).scalars()}
        assert stages["editor"] == stages["publish"] == "success"
        assert all(stages[key] == "skipped" for key in ("collect", "snapshot", "info_analysis", "personal_analysis", "goal_analysis", "advice"))
    history = fclient.get("/api/morning/history").json()["items"]
    assert len(history) == 1 and history[0]["version_no"] == 2


def test_reassemble_api_conflict_and_missing_inputs(fclient):
    sf = fclient.app.state.mr_session_factory
    with sf() as mr:
        source_id = seed(mr)
        run = RunRecord(run_date="2026-11-10", kind="generate", status="running")
        mr.add(run); mr.commit()
    assert fclient.post("/api/morning/reassemble", json={"version_id": source_id}).status_code == 409
    assert fclient.post("/api/morning/reassemble", json={"version_id": 99999}).status_code == 404
    with sf() as mr:
        source = mr.get(ReportVersion, source_id)
        source.sections = {}
        mr.commit()
    result = fclient.post("/api/morning/reassemble", json={"version_id": source_id})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "assembly_input_missing"


def test_reassemble_legacy_uses_saved_news_and_snapshot(fclient):
    from app.morning_report.services.report_actions import assembly_state
    sf = fclient.app.state.mr_session_factory
    with sf() as mr:
        source_id = seed(mr)
        source = mr.get(ReportVersion, source_id)
        sections = dict(source.sections)
        sections.pop("assembly_input")
        sections["news_content"] = {"version": 1, "categories": {"domestic": [{"id": 10, "title": "原始新闻", "url": "https://example.com/old", "summary": "原始摘要"}], "international": [], "ai": []}, "errors": {"ai": "原始缺失原因"}}
        source.sections = sections
        mr.commit()
        state = assembly_state(mr, source)
        assert state["news_errors"] == {"ai": "原始缺失原因"}
        assert state["news"][0]["source_url"] == "https://example.com/old"
        assert state["yesterday_content"] == source.sections["yesterday_content"]


def test_history_latest_published_per_day_keeps_old_and_failed_versions(fclient):
    sf = fclient.app.state.mr_session_factory
    with sf() as mr:
        source_id = seed(mr)
        source = mr.get(ReportVersion, source_id)
        for date, number, status in (("2026-11-10", 2, "published"), ("2026-11-10", 3, "failed"), ("2026-11-11", 1, "published")):
            mr.add(ReportVersion(run_id=source.run_id, report_date=date, version_no=number, status=status, sections={}, content_md="test"))
        mr.commit()
    items = fclient.get("/api/morning/history").json()["items"]
    assert [(item["report_date"], item["version_no"]) for item in items] == [("2026-11-11", 1), ("2026-11-10", 2)]
    with sf() as mr:
        assert len(mr.execute(select(ReportVersion)).scalars().all()) == 4


def test_cancelled_reassembly_never_publishes(fclient):
    import pytest
    from app.morning_report.services.cancel import CancelToken, GenerationCancelled
    sf = fclient.app.state.mr_session_factory
    with sf() as mr:
        source_id = seed(mr)
        token = CancelToken()
        token.cancel()
        with pytest.raises(GenerationCancelled):
            run_reassemble(mr, 99999, source_id, mr_session_factory=sf, cancel_token=token)
        assert len(mr.execute(select(ReportVersion)).scalars().all()) == 1


def test_reassemble_api_submits_same_generation_task_lane(fclient, monkeypatch):
    sf = fclient.app.state.mr_session_factory
    with sf() as mr:
        source_id = seed(mr)
    submitted = []
    monkeypatch.setattr(fclient.app.state.mr_runner, "submit", lambda kind, run_id, fn: submitted.append((kind, run_id, fn)) or True)
    result = fclient.post("/api/morning/reassemble", json={"version_id": source_id})
    assert result.status_code == 202
    assert submitted[0][0] == "generate"
    assert submitted[0][1] == result.json()["run_id"]
    with sf() as mr:
        run = mr.get(RunRecord, result.json()["run_id"])
        assert run.run_date == "2026-11-10" and run.status == "pending"


def test_reassembling_old_date_does_not_replace_current_day_report(fclient):
    sf = fclient.app.state.mr_session_factory
    with sf() as mr:
        source_id = seed(mr)
        source = mr.get(ReportVersion, source_id)
        latest = ReportVersion(run_id=source.run_id, report_date="2026-11-11", version_no=1, status="published", sections={}, content_md="最新一天")
        mr.add(latest); mr.commit(); latest_id = latest.id
        run = RunRecord(run_date="2026-11-10", kind="generate", status="pending")
        mr.add(run); mr.commit()
        run_reassemble(mr, run.id, source_id, mr_session_factory=sf)
    assert fclient.get("/api/morning/report").json()["id"] == latest_id
