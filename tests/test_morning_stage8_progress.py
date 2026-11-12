# -*- coding: utf-8 -*-
"""阶段进度面板后端测试：阶段流转、快照、脱敏、SSE、互斥、中断恢复。"""

from __future__ import annotations

import json
import re

import pytest
from sqlalchemy import select

from app.morning_report.models import RunRecord, RunStage
from app.morning_report.services import progress as progress_mod
from app.morning_report.services.progress import ProgressTracker, sanitize

from tests.test_morning_stage4_graph import FakeLLM, TraceSubagents, NEWS, _deps


def _run(fclient, status="running"):
    with fclient.app.state.mr_session_factory() as mr:
        r = RunRecord(run_date="2026-11-11", kind="generate", status=status)
        mr.add(r)
        mr.commit()
        return r.id


def test_stage_lifecycle(fclient):
    rid = _run(fclient)
    with fclient.app.state.mr_session_factory() as mr:
        t = ProgressTracker(mr, rid)
        t.stage_started("editor", "正在撰写")
        row = mr.execute(select(RunStage).where(RunStage.run_id == rid, RunStage.stage == "editor")).scalars().one()
        assert row.status == "running" and row.title == "正文组装" and row.attempts == 1
        # 重复 started：attempts+1，时间保留
        t.stage_started("editor")
        mr.expire_all()
        assert row.attempts == 2 and row.status == "running"
        t.stage_progress("editor", summary="撰写中 50%")
        t.stage_completed("editor", summary="正文 1200 字", data={"chars": 1200})
        mr.expire_all()
        assert row.status == "success" and row.summary == "正文 1200 字"
        assert row.elapsed_ms is not None and row.data == {"chars": 1200}
        # 降级跳过
        t.stage_completed("goal_analysis", status="skipped", reason="执行失败，按规则降级")
        mr.expire_all()
        tr = mr.execute(select(RunStage).where(RunStage.stage == "goal_analysis")).scalars().one()
        assert tr.status == "skipped" and "降级" in tr.reason


def test_snapshot_covers_all_stages_and_groups(fclient):
    rid = _run(fclient)
    with fclient.app.state.mr_session_factory() as mr:
        t = ProgressTracker(mr, rid)
        t.stage_completed("collect", summary="复用采集", status="skipped", reason="x")
        t.stage_started("editor")
        snap = progress_mod.snapshot(mr, rid, stall_seconds=99)
    assert snap["total_count"] == 8  # 完整阶段列表，含未开始
    statuses = {s["stage"]: s["status"] for s in snap["stages"]}
    assert statuses["collect"] == "skipped" and statuses["editor"] == "running"
    assert "quality_eval" not in statuses
    assert "fact_check" not in statuses
    groups = {s["stage"]: s["group"] for s in snap["stages"]}
    assert groups["goal_analysis"] is None
    assert groups["advice"] is None  # 建议后置，不属于并行组
    assert snap["stall_seconds"] == 99 and snap["server_now"]
    assert snap["done_count"] == 1


def test_sanitize_masks_keys_and_drops_prompts():
    data = {"model": "qwen-flash", "api_key": "sk-abcdef123456", "nested": {"prompt": "秘密",
            "note": "key=sk-zzzzzzzzzzzz here"}, "messages": [{"role": "user"}]}
    out = sanitize(data)
    assert "api_key" not in out and "prompt" not in out["nested"] and "messages" not in out
    assert out["nested"]["note"] == "key=sk-*** here"


def test_legacy_fact_check_stage_is_preserved_but_hidden(fclient):
    rid = _run(fclient, status="success")
    with fclient.app.state.mr_session_factory() as mr:
        mr.add(RunStage(run_id=rid, stage="fact_check", title="事实校验",
                        sort_order=9, status="success"))
        mr.commit()
        snap = progress_mod.snapshot(mr, rid)
        assert snap["total_count"] == 8
        assert all(stage["stage"] != "fact_check" for stage in snap["stages"])
        assert mr.execute(select(RunStage).where(
            RunStage.run_id == rid, RunStage.stage == "fact_check")).scalar_one().status == "success"


def test_seq_changes_on_stage_update_without_new_rows(fclient):
    from app.morning_report.api.progress import _seq_of

    rid = _run(fclient)
    with fclient.app.state.mr_session_factory() as mr:
        tracker = ProgressTracker(mr, rid)
        tracker.stage_started("editor")
        before = _seq_of(mr, rid)
        tracker.stage_failed("editor", "主编失败")
        assert _seq_of(mr, rid) > before


def test_terminal_stream_sends_full_snapshot_even_at_current_seq(fclient):
    from app.morning_report.api.progress import _seq_of

    rid = _run(fclient, status="failed")
    with fclient.app.state.mr_session_factory() as mr:
        ProgressTracker(mr, rid).stage_failed("editor", "主编失败")
        seq = _seq_of(mr, rid)
    with fclient.stream("GET", f"/api/morning/progress/stream?run_id={rid}&after_seq={seq}") as resp:
        frames = [json.loads(m) for m in re.findall(r"data: (.+)", resp.read().decode())]
    assert frames[0]["run"]["status"] == "failed"
    assert frames[0]["active"] is False
    assert frames[-1]["done"] is True


def test_running_stream_observes_terminal_without_new_log_or_stage(fclient, monkeypatch):
    from app.morning_report.api import progress as api

    rid = _run(fclient)
    # 直接驱动生成器，使跨会话写入发生在两帧之间，不依赖真实线程计时。
    monkeypatch.setattr(api, "EventSourceResponse", lambda gen: gen)
    monkeypatch.setattr(api.time, "sleep", lambda _: None)
    with fclient.app.state.mr_session_factory() as mr:
        cached_run = mr.get(RunRecord, rid)
        ProgressTracker(mr, rid).stage_started("editor")
        stream = api.progress_stream(rid, after_seq=0, mr=mr)
        assert json.loads(next(stream)["data"])["run"]["status"] == "running"
        with fclient.app.state.mr_session_factory() as writer:
            run = writer.get(RunRecord, rid)
            run.status = "failed"
            run.error = "主编生成失败"
            writer.commit()
        assert cached_run.status == "running"  # 旧会话确实持有过期对象
        final = json.loads(next(stream)["data"])
        assert final["run"]["status"] == "failed"
        assert final["active"] is False
        assert json.loads(next(stream)["data"])["done"] is True
        with pytest.raises(StopIteration):
            next(stream)


def test_progress_api_snapshot_and_active(fclient):
    rid = _run(fclient)
    with fclient.app.state.mr_session_factory() as mr:
        ProgressTracker(mr, rid).stage_started("editor")
    res = fclient.get("/api/morning/progress", params={"run_id": rid})
    assert res.status_code == 200
    body = res.json()
    assert body["run"]["id"] == rid and body["seq"] > 0
    assert len(body["stages"]) == 8
    act = fclient.get("/api/morning/progress/active", params={"report_date": "2026-11-11"}).json()
    assert act["active"] is True and act["run"]["id"] == rid
    # 终态后 active=False
    with fclient.app.state.mr_session_factory() as mr:
        mr.get(RunRecord, rid).status = "success"
        mr.commit()
    act = fclient.get("/api/morning/progress/active", params={"report_date": "2026-11-11"}).json()
    assert act["active"] is False


def test_progress_stream_snapshot_then_done(fclient):
    rid = _run(fclient, status="success")
    with fclient.app.state.mr_session_factory() as mr:
        t = ProgressTracker(mr, rid)
        t.stage_completed("publish", summary="v1 已发布")
    with fclient.stream("GET", f"/api/morning/progress/stream?run_id={rid}&after_seq=0") as resp:
        assert resp.status_code == 200
        chunks = []
        for chunk in resp.iter_text():
            chunks.append(chunk)
            joined = "".join(chunks)
            if '"done": true' in joined:
                break
    frames = [json.loads(m) for m in re.findall(r"data: (.+)", "".join(chunks))]
    snaps = [f for f in frames if "stages" in f]
    dones = [f for f in frames if f.get("done")]
    assert snaps and dones, "应先推快照再推 done"
    assert snaps[-1]["stages"][-1]["status"] == "success"  # publish 完成
    assert dones[-1]["status"] == "success"
    # seq 单调
    seqs = [f["seq"] for f in snaps]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_progress_stream_incremental_no_duplicate(fclient):
    rid = _run(fclient, status="success")
    with fclient.app.state.mr_session_factory() as mr:
        t = ProgressTracker(mr, rid)
        t.stage_completed("collect", summary="a")
        seq1 = progress_mod_progress_seq(mr, rid)
        t.stage_completed("snapshot", summary="b")
        seq2 = progress_mod_progress_seq(mr, rid)
    with fclient.stream("GET", f"/api/morning/progress/stream?run_id={rid}&after_seq={seq1}") as resp:
        text = ""
        for chunk in resp.iter_text():
            text += chunk
            if '"done": true' in text:
                break
    frames = [json.loads(m) for m in re.findall(r"data: (.+)", text)]
    snaps = [f for f in frames if "stages" in f]
    assert all(f["seq"] > seq1 for f in snaps), "只推增量（seq > after_seq）"
    assert snaps[0]["stages"][0]["status"] == "success"  # 补发后 collect 已完成


def progress_mod_progress_seq(mr, rid):
    from app.morning_report.api.progress import _seq_of
    return _seq_of(mr, rid)


def test_regenerate_mutex_while_running(fclient):
    """活动任务存在时 regenerate 返回 409（后端互斥，不依赖前端禁用）。"""
    _run(fclient, status="running")
    res = fclient.post("/api/morning/regenerate", json={"mode": "reuse"})
    assert res.status_code == 409


def test_interrupt_stale_stages(fclient):
    rid = _run(fclient, status="running")
    with fclient.app.state.mr_session_factory() as mr:
        t = ProgressTracker(mr, rid)
        t.stage_started("editor")
        t.stage_started("advice")
        n = progress_mod.interrupt_stale_stages(mr)
        assert n == 2
        rows = mr.execute(select(RunStage).where(RunStage.run_id == rid)).scalars().all()
        assert all(r.status == "interrupted" and "待确认" in (r.reason or "") for r in rows)
        # 幂等
        assert progress_mod.interrupt_stale_stages(mr) == 0


def test_run_generate_writes_stage_flow(fclient):
    """端到端（假 LLM）：验证完整阶段流转与并行子代理状态。"""
    from app.morning_report.config import MRSettings
    from app.morning_report.models import NewsItem
    from app.morning_report.services import news_pipeline, report_service

    # 窗口需与 NEWS 的发布时间匹配（11-09 10:00/17:38 → 报告日 2026-11-10）
    with fclient.app.state.mr_session_factory() as mr:
        collect = news_pipeline.create_collect_run(mr, "2026-11-10")
        for n in NEWS:
            raw = ({"daily_member": True, "daily_date": "2026-11-10", "display_order": 1,
                    "daily_kind": "section", "section_label": "模型发布/更新"}
                   if n["category"] == "ai" else {})
            mr.add(NewsItem(run_id=collect.id, category=n["category"], title=n["title"],
                            summary=n["summary"], source_name=n["source_name"],
                            source_url=n["source_url"], published_at=n["published_at"],
                            content_hash=n["content_hash"], dedupe_status="unique", raw_ref=raw))
        collect.status = "success"  # 标记采集已完成，避免 run_generate 触发真实补采
        run = RunRecord(run_date="2026-11-10", kind="generate", status="pending")
        mr.add(run)
        mr.commit()
        rid = run.id
    deps = _deps(fclient, llm=FakeLLM(), subagents=TraceSubagents(), run_id=rid)
    settings = MRSettings(schedule_enabled=False)
    with fclient.app.state.mr_session_factory() as mr:
        report_service.run_generate(
            mr, rid, settings, mode="manual", deps_override=deps,
            hub_session_factory=None,
            mr_session_factory=fclient.app.state.mr_session_factory)
    with fclient.app.state.mr_session_factory() as mr:
        snap = progress_mod.snapshot(mr, rid)
    statuses = {s["stage"]: s["status"] for s in snap["stages"]}
    # 并行 Subagent 都真实执行完成（独立状态，非顺序伪装）
    assert "tech_research" not in statuses
    assert statuses["goal_analysis"] == "success"
    assert statuses["advice"] == "success"
    assert statuses["editor"] == "success"
    assert "fact_check" not in statuses
    assert "quality_eval" not in statuses
    assert statuses["publish"] == "success"
    assert snap["run"]["status"] == "success"
    collect_stage = next(s for s in snap["stages"] if s["stage"] == "collect")
    assert collect_stage["data"]["by_category"] == {"domestic": 1, "international": 1, "ai": 1}
    assert collect_stage["data"]["saved"] == 3


def test_empty_active_progress_returns_complete_contract(fclient):
    response = fclient.get("/api/morning/progress/active")
    assert response.status_code == 200
    data = response.json()
    assert data["run"] is None and data["active"] is False
    assert data["recent"] == [] and data["stages"] == []
    assert data["done_count"] == data["total_count"] == data["seq"] == 0
    assert data["server_now"] and data["stall_seconds"] > 0
