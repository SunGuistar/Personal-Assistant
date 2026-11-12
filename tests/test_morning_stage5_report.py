# -*- coding: utf-8 -*-
"""阶段 5 验收：报告/评价/历史 API、重新生成语义、个人事件快照、用量统计。"""

from __future__ import annotations

from sqlalchemy import select

from app.morning_report.models import (Evaluation, PersonalEventSnapshot,
                                       ReportVersion, RunRecord, StageCache, TokenUsage)
from app.morning_report.services import report_service, stage_cache

from tests.test_morning_stage4_graph import FakeLLM, TraceSubagents, NEWS, _deps

MD1 = "# 今日晨报\n\n## 一、开篇速览\n\n内容A。\n"
MD2 = "# 今日晨报\n\n## 一、开篇速览\n\n内容B（修正版）。\n"


def _seed_two_versions(fclient):
    with fclient.app.state.mr_session_factory() as mr:
        run = RunRecord(run_date="2026-11-10", kind="generate", status="success")
        mr.add(run)
        mr.flush()
        v1 = ReportVersion(run_id=run.id, report_date="2026-11-10", version_no=1,
                           is_primary=True, status="published", title="晨报",
                           sections={}, content_md=MD1, snapshot_id="s1")
        v2 = ReportVersion(run_id=run.id, report_date="2026-11-10", version_no=2,
                           is_primary=False, status="published", title="晨报",
                           sections={}, content_md=MD2, snapshot_id="s2")
        mr.add_all([v1, v2])
        mr.flush()
        mr.add(Evaluation(version_id=v2.id, status="ok",
                          scores={"资讯呈现": 80, "内容逻辑与一致性": 82, "AI 技术分析": 78,
                                  "个人总结与建议": 81, "阅读体验": 79},
                          composite=80, comment="良好", model="qwen-flash",
                          rule_version="quality_score_v1"))
        mr.commit()
        return v1.id, v2.id


def test_report_api_latest_and_explicit_version(fclient):
    v1_id, v2_id = _seed_two_versions(fclient)
    primary = fclient.get("/api/morning/report", params={"report_date": "2026-11-10"})
    assert primary.status_code == 200
    body = primary.json()
    assert "fact_check" not in body
    assert body["is_primary"] is False and body["version_no"] == 2
    assert "内容B" in body["content_md"]
    latest = fclient.get("/api/morning/report")
    assert latest.status_code == 200 and latest.json()["id"] == v2_id
    old = fclient.get("/api/morning/report", params={"report_date": "2026-11-10", "version_no": 1})
    assert old.json()["id"] == v1_id and "内容A" in old.json()["content_md"]

    specific = fclient.get("/api/morning/report", params={"report_date": "2026-11-10", "version_no": 2})
    assert specific.json()["id"] == v2_id
    assert specific.json()["evaluation"]["composite"] == 80
    assert specific.json()["evaluation"]["rule_version"] == "quality_score_v1"

    missing = fclient.get("/api/morning/report", params={"report_date": "2026-11-09"})
    assert missing.status_code == 404


def test_history_lists_versions(fclient):
    _seed_two_versions(fclient)
    res = fclient.get("/api/morning/history")
    items = res.json()["items"]
    assert len(items) == 2
    assert items[0]["version_no"] == 2  # 最新在前
    assert any(i["has_evaluation"] for i in items)


def test_regenerate_conflict_guard(fclient):
    """已有生成在运行时 regenerate 返回 409。"""
    with fclient.app.state.mr_session_factory() as mr:
        mr.add(RunRecord(run_date="2026-11-10", kind="generate", status="running"))
        mr.commit()
    res = fclient.post("/api/morning/regenerate", json={"mode": "reuse"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "task_conflict"


def test_clear_cache_semantics(fclient):
    """auto/full 清缓存；manual 默认复用。"""
    from app.morning_report.config import MRSettings

    with fclient.app.state.mr_session_factory() as mr:
        stage_cache.put_cache(mr, "n", "fp", {"a": 1})
        assert mr.execute(select(StageCache)).scalars().all() != []
        run = RunRecord(run_date="2026-11-10", kind="generate", status="pending")
        mr.add(run)
        mr.commit()
        rid = run.id
        from app.morning_report.services import news_pipeline
        collect = news_pipeline.create_collect_run(mr, "2026-11-10")
        collect.status = "success"
        from app.morning_report.models import NewsItem
        for n in NEWS:
            mr.add(NewsItem(run_id=collect.id, category=n["category"], title=n["title"],
                            summary=n["summary"], source_name=n["source_name"],
                            source_url=n["source_url"], published_at=n["published_at"],
                            content_hash=n["content_hash"], dedupe_status="unique", raw_ref={}))
        mr.commit()

    deps = _deps(fclient, run_id=rid)
    settings = MRSettings(schedule_enabled=False)
    with fclient.app.state.mr_session_factory() as mr:
        stage_cache.put_cache(mr, "n", "fp", {"a": 1})
        report_service.run_generate(mr, rid, settings, mode="manual",
                                    deps_override=deps, hub_session_factory=None,
                                    mr_session_factory=fclient.app.state.mr_session_factory)
    with fclient.app.state.mr_session_factory() as mr:
        # manual 不清缓存
        assert mr.execute(select(StageCache).where(StageCache.node_key == "n")).scalars().all() != []

    with fclient.app.state.mr_session_factory() as mr:
        run2 = RunRecord(run_date="2026-11-10", kind="generate", status="pending")
        mr.add(run2)
        mr.commit()
        rid2 = run2.id
    deps2 = _deps(fclient, run_id=rid2)
    with fclient.app.state.mr_session_factory() as mr:
        report_service.run_generate(mr, rid2, settings, mode="manual",
                                    deps_override=deps2, hub_session_factory=None,
                                    mr_session_factory=fclient.app.state.mr_session_factory,
                                    clear_cache=True)
    with fclient.app.state.mr_session_factory() as mr:
        assert mr.execute(select(StageCache).where(StageCache.node_key == "n")).scalars().all() == []


def test_personal_snapshot_and_usage(fclient):
    """run_generate 写入个人事件快照；Token 用量可经 API 查询。"""
    from app.morning_report.config import MRSettings

    with fclient.app.state.mr_session_factory() as mr:
        run = RunRecord(run_date="2026-11-10", kind="generate", status="pending")
        mr.add(run)
        mr.commit()
        rid = run.id
        from app.morning_report.services import news_pipeline
        collect = news_pipeline.create_collect_run(mr, "2026-11-10")
        collect.status = "success"
        from app.morning_report.models import NewsItem
        for n in NEWS:
            mr.add(NewsItem(run_id=collect.id, category=n["category"], title=n["title"],
                            summary=n["summary"], source_name=n["source_name"],
                            source_url=n["source_url"], published_at=n["published_at"],
                            content_hash=n["content_hash"], dedupe_status="unique", raw_ref={}))
        mr.commit()

    class CountingLLM(FakeLLM):
        def __init__(self):
            super().__init__()
            self.recorder_calls = 0

    deps = _deps(fclient, run_id=rid)

    def recorder(node, result, model, base_url):
        with fclient.app.state.mr_session_factory() as s:
            s.add(TokenUsage(run_id=rid, node=node, provider="fake", model=model,
                             input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                             elapsed_ms=result.elapsed_ms))
            s.commit()

    deps.recorder = recorder
    settings = MRSettings(schedule_enabled=False)

    personal_ctx = {"daily_done": [{"id": 7, "title": "读完 LangGraph 文档",
                                    "completed_at": "2026-11-09T09:00:00+08:00"}],
                    "daily_pending": [], "longterm_highlight": [{"id": 3, "title": "晨报 V2 上线"}],
                    "longterm_active": [], "important_infos": []}

    with fclient.app.state.mr_session_factory() as mr:
        report_service.run_generate(mr, rid, settings, mode="manual",
                                    deps_override=deps, hub_session_factory=None,
                                    personal_ctx_override=personal_ctx,
                                    mr_session_factory=fclient.app.state.mr_session_factory)

    with fclient.app.state.mr_session_factory() as mr:
        snaps = mr.execute(select(PersonalEventSnapshot)).scalars().all()
        assert any(s.record_id == 7 and s.source_table == "daily_tasks" for s in snaps)
        assert all(s.snapshot_id for s in snaps)

    res = fclient.get("/api/morning/usage", params={"run_id": rid})
    assert res.status_code == 200
    body = res.json()
    # 当前新闻/个人准备为确定性步骤，假 Subagent 不产生模型用量；只记录主编与评价。
    assert {item["node"] for item in body["items"]} == {"editor", "quality_eval"}
    assert body["totals"]["calls"] == len(body["items"]) == 2
    assert body["totals"]["input_tokens"] == 20
    usage_all = fclient.get("/api/morning/usage")
    assert usage_all.json()["totals"]["calls"] >= body["totals"]["calls"]
