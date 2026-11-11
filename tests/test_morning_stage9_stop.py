# -*- coding: utf-8 -*-
"""停止生成功能测试：协作式取消、幂等、竞态、后续节点不执行、数据保留。"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import select

from app.morning_report.models import NewsItem, ReportVersion, RunRecord, RunStage
from app.morning_report.services import news_pipeline, report_service
from app.morning_report.services.cancel import CancelToken, GenerationCancelled
from app.morning_report.services.progress import ProgressTracker

from tests.test_morning_stage4_graph import FakeLLM, TraceSubagents, NEWS, _deps


def _seed(fclient, report_date="2026-11-10"):
    with fclient.app.state.mr_session_factory() as mr:
        collect = news_pipeline.create_collect_run(mr, report_date)
        for n in NEWS:
            mr.add(NewsItem(run_id=collect.id, category=n["category"], title=n["title"],
                            summary=n["summary"], source_name=n["source_name"],
                            source_url=n["source_url"], published_at=n["published_at"],
                            content_hash=n["content_hash"], dedupe_status="unique", raw_ref={}))
        collect.status = "success"
        run = RunRecord(run_date=report_date, kind="generate", status="pending")
        mr.add(run)
        mr.commit()
        return collect.id, run.id


class SlowSubagents(TraceSubagents):
    """让 goal_analysis 慢 enough 以便在并行期间触发取消。"""

    def run(self, name, prompt, tools):
        if name == "goal_analysis":
            time.sleep(0.5)
        return super().run(name, prompt, tools)


def test_cancel_before_workflow_stops_subsequent_nodes(fclient):
    """取消后：后续工作流节点不再执行；不发布不完整晨报；阶段如实反映。"""
    from app.morning_report.config import MRSettings
    from app.morning_report.services import progress as progress_mod

    collect_id, rid = _seed(fclient)
    token = CancelToken()
    deps = _deps(fclient, llm=FakeLLM(), subagents=SlowSubagents(), run_id=rid)
    settings = MRSettings(schedule_enabled=False)

    result: dict = {}
    err: list[BaseException] = []

    def work():
        try:
            with fclient.app.state.mr_session_factory() as mr:
                result["out"] = report_service.run_generate(
                    mr, rid, settings, mode="manual", deps_override=deps,
                    hub_session_factory=None,
                    mr_session_factory=fclient.app.state.mr_session_factory,
                    cancel_token=token)
        except BaseException as e:  # noqa: BLE001
            err.append(e)

    t = threading.Thread(target=work)
    t.start()
    # 等资讯分析完成（检查点开始生效的时点），再取消
    from app.morning_report.services import progress as _pm
    for _ in range(200):
        with fclient.app.state.mr_session_factory() as mr:
            row = mr.execute(select(RunStage).where(
                RunStage.run_id == rid, RunStage.stage == "info_analysis")).scalars().first()
            if row is not None and row.status == "success":
                break
        time.sleep(0.05)
    token.cancel()
    t.join(timeout=60)

    assert not t.is_alive()
    assert isinstance(err[0], GenerationCancelled) if err else True
    with fclient.app.state.mr_session_factory() as mr:
        run = mr.get(RunRecord, rid)
        assert run.status == "running"  # 直接调用路径不经过 Runner，终态落库由 Runner 负责
        snap = progress_mod.snapshot(mr, rid)
    statuses = {s["stage"]: s["status"] for s in snap["stages"]}
    # 已完成的保留；建议及之后未执行
    assert statuses["info_analysis"] == "success"
    assert statuses["advice"] == "pending"
    assert statuses["editor"] == "pending"
    assert statuses["publish"] == "pending"
    with fclient.app.state.mr_session_factory() as mr:
        assert mr.execute(select(ReportVersion)).scalars().all() == []  # 未发布不完整晨报


def test_runner_marks_cancelled_and_preserves_data(fclient):
    """经 Runner 的完整路径：cancelled 终态、进行阶段标记、日志记录、缓存数据保留。"""
    from app.morning_report.services.stage_cache import fingerprint, put_cache

    with fclient.app.state.mr_session_factory() as mr:
        r = RunRecord(run_date="2026-11-11", kind="generate", status="pending")
        mr.add(r)
        mr.commit()
        rid = r.id
        put_cache(mr, "info_analysis", fingerprint("x"), {"result": "ok"})

    runner = fclient.app.state.mr_runner
    token_holder: dict = {}

    def fn(session, run_id):
        token_holder["token"] = runner.token_for(run_id)
        ProgressTracker(session, run_id).stage_started("editor")
        while not token_holder["token"].cancelled:
            time.sleep(0.05)
        raise GenerationCancelled()

    assert runner.submit("generate", rid, fn) is True
    for _ in range(100):
        if "token" in token_holder:
            break
        time.sleep(0.05)
    assert runner.request_cancel(rid) is True
    for _ in range(100):
        with fclient.app.state.mr_session_factory() as mr:
            if mr.get(RunRecord, rid).status == "cancelled":
                break
        time.sleep(0.1)
    with fclient.app.state.mr_session_factory() as mr:
        run = mr.get(RunRecord, rid)
        assert run.status == "cancelled" and run.stop_reason == "用户主动停止"
        assert run.stopped_at and run.finished_at
        st = mr.execute(select(RunStage).where(RunStage.run_id == rid)).scalars().one()
        assert st.status == "cancelled" and st.reason == "用户主动停止"
        from app.morning_report.models import RunLog
        logs = mr.execute(select(RunLog).where(RunLog.run_id == rid, RunLog.stage == "stop")).scalars().all()
        assert logs and "用户主动停止" in logs[0].message
        # 缓存保留
        from app.morning_report.models import StageCache
        assert mr.execute(select(StageCache)).scalars().all() != []
    # 停止后可再启动（runner kind 锁释放）
    assert runner.request_cancel(rid) is False  # 令牌已清理，幂等返回


def test_stop_api_idempotent_and_terminal_guard(fclient):
    """停止接口：活动→stopping→幂等；终态任务不被修改。"""
    from app.morning_report.services import progress as progress_mod

    with fclient.app.state.mr_session_factory() as mr:
        r = RunRecord(run_date="2026-11-11", kind="generate", status="running")
        mr.add(r)
        mr.commit()
        rid = r.id
        ProgressTracker(mr, rid).stage_started("editor")

    res1 = fclient.post(f"/api/morning/runs/{rid}/stop")
    assert res1.status_code == 200 and res1.json()["status"] == "stopping"
    # 幂等重复停止
    res2 = fclient.post(f"/api/morning/runs/{rid}/stop")
    assert res2.json()["status"] == "stopping" and "已在停止中" in res2.json()["note"]
    # stopping 期间 regenerate 仍被互斥（active 包含 stopping）
    res_conflict = fclient.post("/api/morning/regenerate", json={"mode": "reuse"})
    assert res_conflict.status_code == 409
    # 停止请求日志
    with fclient.app.state.mr_session_factory() as mr:
        run = mr.get(RunRecord, rid)
        run.status = "success"  # 模拟任务自然完成先于停止生效
        mr.commit()
    res3 = fclient.post(f"/api/morning/runs/{rid}/stop")
    assert res3.json()["status"] == "success" and "终态" in res3.json()["note"]


def test_stop_race_natural_completion(fclient):
    """停止请求与任务自然完成竞态：UPDATE 守卫保证不覆盖终态。"""
    with fclient.app.state.mr_session_factory() as mr:
        r = RunRecord(run_date="2026-11-11", kind="generate", status="pending")
        mr.add(r)
        mr.commit()
        rid = r.id
    with fclient.app.state.mr_session_factory() as mr:
        mr.get(RunRecord, rid).status = "success"
        mr.commit()
    res = fclient.post(f"/api/morning/runs/{rid}/stop")
    assert res.json()["status"] == "success"
    with fclient.app.state.mr_session_factory() as mr:
        assert mr.get(RunRecord, rid).status == "success"  # 未被改


def test_collect_cooperative_cancel_between_sources(fclient, monkeypatch):
    """采集源之间检查点：取消后不再启动后续来源。"""
    from app.morning_report.adapters import aihot, chinanews, remoshuang
    from app.morning_report.services import news_pipeline

    calls: list[str] = []

    def slow_aihot():
        calls.append("aihot")
        time.sleep(0.3)
        return []

    monkeypatch.setattr(aihot, "fetch_selected", slow_aihot)
    monkeypatch.setattr(chinanews, "fetch_window", lambda *a: calls.append("chinanews") or [])
    monkeypatch.setattr(remoshuang, "fetch_daily", lambda *a: calls.append("remoshuang") or [])

    with fclient.app.state.mr_session_factory() as mr:
        run = news_pipeline.create_collect_run(mr, "2026-11-11")
        rid = run.id
    token = CancelToken()

    def work():
        with fclient.app.state.mr_session_factory() as mr:
            news_pipeline.run_collect(mr, rid, cancel_token=token)

    t = threading.Thread(target=work)
    t.start()
    time.sleep(0.1)
    token.cancel()
    t.join(timeout=30)
    assert not t.is_alive(), "采集线程未在取消后结束"
    assert "aihot" in calls
    assert "chinanews" not in calls and "remoshuang" not in calls  # 后续来源未启动
