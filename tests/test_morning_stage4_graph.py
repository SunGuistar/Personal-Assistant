# -*- coding: utf-8 -*-
"""阶段 4 验收：LangGraph 全流程（假 LLM/Subagent，真图编排/Checkpoint/缓存/发布幂等）。"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select

from app.morning_report.graph.workflow import WorkflowDeps, build_workflow
from app.morning_report.models import Evaluation, ReportVersion, StageCache, TokenUsage
from app.morning_report.services import report_service
from app.morning_report.services.llm_router import ChatResult, is_allowed_period

NEWS = [
    {"id": 1, "category": "domestic", "title": "国常会部署经济工作", "summary": "部署稳增长",
     "source_name": "中新网", "source_url": "https://example.com/d1",
     "published_at": "2026-11-09T10:00:00+08:00", "content_hash": "h1", "event_group_id": None},
    {"id": 2, "category": "international", "title": "特朗普宣布铁门行动", "summary": "美伊局势",
     "source_name": "中新网", "source_url": "https://example.com/i1",
     "published_at": "2026-11-09T17:38:00+08:00", "content_hash": "h2", "event_group_id": None},
    {"id": 3, "category": "ai", "title": "LangGraph 0.6 发布", "summary": "新增中断恢复",
     "source_name": "GitHub", "source_url": "https://example.com/a1",
     "published_at": "2026-11-09T10:00:00+08:00", "content_hash": "h3", "event_group_id": None},
]

REPORT_MD = """# 今日晨报

## 一、开篇速览
本期关注 [国常会部署](https://example.com/d1) 等。

## 二、重要资讯
### 国内
[国常会部署经济工作](https://example.com/d1)：部署稳增长。
### 国际
[特朗普宣布铁门行动](https://example.com/i1)：美伊局势。
### AI
本期 AI 进展概览。
{{AI_NEWS_LIST}}

## 三、我的昨日
按计划推进，无异常。

## 四、今日建议
1. 继续推进长期计划

## 五、信息说明
窗口 2026-11-09 08:00 ~ 2026-11-10 08:00；来源见链接。
"""

AI_DAILY = [
    {"id": 3, "title": "LangGraph 0.6 发布", "summary": "新增中断恢复",
     "source_name": "GitHub", "url": "https://example.com/a1",
     "section_label": "模型发布/更新", "daily_kind": "section",
     "published_at": "2026-11-09T10:00:00+08:00"},
]


class FakeLLM:
    model = "fake-llm"
    base_url = "fake://local"

    def __init__(self, fail_eval: bool = False):
        self.calls: list[str] = []
        self.fail_eval = fail_eval

    def chat(self, messages, *, json_mode=False, tools=None, thinking=None):
        prompt = messages[-1]["content"]
        self.calls.append(prompt[:120])
        if "选出值得进入晨报的条目" in prompt:
            content = json.dumps({
                "domestic": [{"id": 1, "title": "国常会部署经济工作", "why": "重要政策"}],
                "international": [{"id": 2, "title": "特朗普宣布铁门行动", "why": "重大国际"}],
                "ai": [{"id": 3, "title": "LangGraph 0.6 发布", "why": "实质进展", "value": "中断恢复能力"}],
            }, ensure_ascii=False)
        elif "总结昨日进展" in prompt:
            content = "昨日完成既定任务，长期计划推进正常。"
        elif "给出 0-3 条" in prompt:
            content = json.dumps({"advices": [{"content": "继续推进长期计划", "basis": "目标分析"}],
                                  "note": ""}, ensure_ascii=False)
        elif "五部分结构" in prompt:
            content = json.dumps({"content_md": REPORT_MD}, ensure_ascii=False)
        elif "七个维度各打" in prompt:
            if self.fail_eval:
                raise RuntimeError("评价模型不可用")
            content = json.dumps({"scores": {"资讯完整性": 88, "信息准确性": 86,
                                             "个人分析": 90, "目标关联": 84, "行动价值": 87, "逻辑一致性": 87, "阅读体验": 87},
                                  "comment": "整体质量良好。"}, ensure_ascii=False)
        else:
            content = "……"
        return ChatResult(content=content, input_tokens=10, output_tokens=20, elapsed_ms=5)


class TraceSubagents:
    """记录执行轨迹：断言两个 Agent 的真实顺序。"""

    def __init__(self, fail_first: dict | None = None):
        self.events: list[tuple[str, float]] = []
        self._fail_first = fail_first or {}
        self._failed: set[str] = set()

    def run(self, name, prompt, tools):
        import time

        t0 = time.perf_counter()
        self.events.append((f"{name}:start", t0))
        if name in self._fail_first and name not in self._failed:
            self._failed.add(name)
            raise RuntimeError(f"{name} 首次失败（注入）")
        time.sleep(0.05)
        self.events.append((f"{name}:end", time.perf_counter()))
        return json.dumps({"current_state": {"content": "现有记录不足以验证完整个人进展", "kind": "unknown", "evidence_ids": []}, "progress": [], "risks": [], "goal_observations": [], "associations": [], "questions": [], "data_gaps": []} if name == "goal_analysis" else {"advices": [], "note": "没有足够依据，不凑数"}, ensure_ascii=False)


def _deps(fclient, llm=None, subagents=None, run_id=1):
    return WorkflowDeps(
        llm=llm or FakeLLM(),
        subagents=subagents or TraceSubagents(),
        mr_session_factory=fclient.app.state.mr_session_factory,
        run_id=run_id,
    )


def _initial(run_id=1):
    return {
        "run_id": run_id, "snapshot_id": "snap-x", "report_date": "2026-11-10",
        "window_start": "2026-11-09T08:00:00+08:00", "window_end": "2026-11-10T08:00:00+08:00",
        "news": NEWS, "clues": [], "ai_daily": AI_DAILY,
        "personal": {"daily_done": [{"id": 1, "source_id": "daily_tasks:1", "title": "读论文", "done": True}], "longterm_highlight": [],
                     "longterm_active": [], "important_infos": []},
    }


def test_allowed_period_rule():
    from datetime import datetime, timezone, timedelta

    cst = timezone(timedelta(hours=8))
    ok, _ = is_allowed_period(datetime(2026, 11, 10, 8, 0, tzinfo=cst))  # 周二 08:00 低谷
    assert ok
    ok, reason = is_allowed_period(datetime(2026, 11, 10, 15, 0, tzinfo=cst))  # 高峰
    assert not ok and "peak" in reason
    ok, _ = is_allowed_period(datetime(2026, 11, 14, 15, 0, tzinfo=cst))  # 周六
    assert ok


def test_full_workflow_publish(fclient):
    deps = _deps(fclient)
    final = asyncio.run(_run_graph(fclient, deps, _initial()))
    assert "fact_check" not in final
    assert "evaluation" not in final
    assert final["publish"]["is_primary"] is True and final["publish"]["version_no"] == 1

    with fclient.app.state.mr_session_factory() as mr:
        ver = mr.get(ReportVersion, final["publish"]["version_id"])
        assert ver.status == "published" and "# 今日晨报" in ver.content_md
        # AI 小节由系统按当期日报组装注入：标题与链接与落库日报一致，不经模型复述
        assert "- [LangGraph 0.6 发布](https://example.com/a1)" in ver.content_md
        assert "{{AI_NEWS_LIST}}" not in ver.content_md
        assert mr.execute(select(Evaluation).where(Evaluation.version_id == ver.id)).first() is None
        # 两个核心 Agent 均执行，技术研究不再调用
    deps.subagents.events  # goal/advice 事件存在
    starts = [t for e, t in deps.subagents.events if e.endswith(":start")]
    assert not any(e.startswith("tech_research") for e, _ in deps.subagents.events)
    assert any(e.startswith("advice") for e, _ in deps.subagents.events)
    assert any(e.startswith("goal_analysis") for e, _ in deps.subagents.events)


def test_second_version_not_primary(fclient):
    """同日再次生成 → 附加版本，不覆盖主报告。"""
    deps = _deps(fclient)
    f1 = asyncio.run(_run_graph(fclient, deps, _initial(run_id=1)))
    deps2 = _deps(fclient, run_id=2)
    f2 = asyncio.run(_run_graph(fclient, deps2, _initial(run_id=2)))
    assert f2["publish"]["version_no"] == 2 and f2["publish"]["is_primary"] is False
    with fclient.app.state.mr_session_factory() as mr:
        v1 = mr.get(ReportVersion, f1["publish"]["version_id"])
        assert v1.is_primary is True  # 原主报告未被覆盖
        versions = mr.execute(select(ReportVersion)).scalars().all()
        assert len([v for v in versions if v.is_primary]) == 1


@pytest.mark.parametrize("published_at", [None, "2026-11-01T10:00:00+08:00"])
def test_publish_without_fact_check_for_unknown_or_old_time(fclient, published_at):
    deps = _deps(fclient)
    initial = _initial()
    initial["news"] = [{**n, "published_at": published_at} for n in NEWS]
    graph = build_workflow(deps).compile()
    assert "fact_check" not in graph.nodes
    final = asyncio.run(_run_graph(fclient, deps, initial))
    assert "fact_check" not in final
    assert final["publish"]["version_no"] == 1
    assert not any("事实与引用校验" in call for call in deps.llm.calls)
    with fclient.app.state.mr_session_factory() as mr:
        version = mr.get(ReportVersion, final["publish"]["version_id"])
        assert version.status == "published"
        assert version.fact_check is None  # 历史列保留，新版本不写入


def test_removed_evaluation_is_never_called(fclient):
    deps = _deps(fclient, llm=FakeLLM(fail_eval=True))
    final = asyncio.run(_run_graph(fclient, deps, _initial()))
    assert final["publish"]["version_no"] == 1
    assert "evaluation" not in final
    assert not any("七个维度各打" in prompt for prompt in deps.llm.calls)
    with fclient.app.state.mr_session_factory() as mr:
        assert mr.execute(select(Evaluation)).first() is None


def test_subagent_failure_degrades(fclient):
    """Subagent 失败 → 节点降级（结论缺失），图继续完成并发布。"""
    deps = _deps(fclient, subagents=TraceSubagents(fail_first={"goal_analysis": True}))
    final = asyncio.run(_run_graph(fclient, deps, _initial()))
    assert final["goal_result"]["status"] == "failed"
    assert final["publish"]["version_no"] == 1  # 降级不阻塞发布


def test_advice_after_subagents(fclient):
    deps = _deps(fclient)
    asyncio.run(_run_graph(fclient, deps, _initial()))
    names = [e for e, _ in deps.subagents.events]
    # ActionSuggest 走 Subagent Runner，并在 GoalAnalysis 完成后执行
    assert names.index("goal_analysis:end") < names.index("advice:start")
    assert any(e.startswith("goal_analysis") for e in names)


def test_deterministic_preparation_needs_no_model_or_stage_cache(fclient):
    llm = FakeLLM()
    deps1 = _deps(fclient, llm=llm, run_id=1)
    asyncio.run(_run_graph(fclient, deps1, _initial(run_id=1)))
    n_after_first = len(llm.calls)
    # 同样输入再次执行：资讯/个人准备仍零模型，两个 Agent 正常获取上下文
    deps2 = _deps(fclient, llm=llm, run_id=2)
    asyncio.run(_run_graph(fclient, deps2, _initial(run_id=2)))
    info_calls_1 = sum(1 for c in llm.calls[:n_after_first] if "选出值得进入晨报" in c)
    info_calls_2 = sum(1 for c in llm.calls[n_after_first:] if "选出值得进入晨报" in c)
    assert info_calls_1 == 0 and info_calls_2 == 0
    assert len(llm.calls) == 0  # 主编及资讯整理均为程序步骤
    assert [e for e, _ in deps2.subagents.events] == ["goal_analysis:start", "goal_analysis:end", "advice:start", "advice:end"]
    with fclient.app.state.mr_session_factory() as mr:
        assert mr.execute(select(StageCache)).scalars().all() == []  # 不缓存伪造的模型资讯分析


async def _run_graph(fclient, deps, initial):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = fclient.app.state.mr_engine.url.database
    g = build_workflow(deps).compile()
    async with AsyncSqliteSaver.from_conn_string(f"{db_path}.ckpt") as saver:
        g = build_workflow(deps).compile(checkpointer=saver)
        return await g.ainvoke(
            initial, config={"configurable": {"thread_id": f"mr-run-{initial['run_id']}"}})


def test_checkpoint_resume_after_editor_failure(fclient, monkeypatch):
    """目标分析首次失败 → 修复后 invoke(None) 恢复，图到达终态。"""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = fclient.app.state.mr_engine.url.database
    # 在主编节点注入失败（无 try/except，异常传播出图）
    llm = FakeLLM()

    from app.morning_report.graph import workflow as workflow_mod
    original_editor = workflow_mod.node_editor
    attempts = []
    def flaky_editor(state, deps):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("程序组装首次失败（注入）")
        return original_editor(state, deps)
    monkeypatch.setattr(workflow_mod, "node_editor", flaky_editor)
    deps = _deps(fclient, llm=llm)
    g = build_workflow(deps).compile()

    async def scenario():
        async with AsyncSqliteSaver.from_conn_string(f"{db_path}.ckpt-resume") as saver:
            g2 = build_workflow(deps).compile(checkpointer=saver)
            cfg = {"configurable": {"thread_id": "mr-resume-1"}}
            with pytest.raises(RuntimeError):
                await g2.ainvoke(_initial(), config=cfg)
            final = await g2.ainvoke(None, config=cfg)  # 修复后恢复
            return final

    final = asyncio.run(scenario())
    assert final["publish"]["version_no"] == 1
    assert "fact_check" not in final


def test_run_generate_publishes_without_fact_check(fclient):
    """report_service 不再依赖事实校验结果即可完成发布。"""
    from sqlalchemy import event
    from app.morning_report.models import Memory, RunRecord
    from app.morning_report.services import news_pipeline

    with fclient.app.state.mr_session_factory() as mr:
        collect = news_pipeline.create_collect_run(mr, "2026-11-10")
        collect.status = "success"  # 预置数据只用于生成，禁止意外启动真实采集
        run = RunRecord(run_date="2026-11-10", kind="generate", status="pending")
        mr.add(Memory(kind="interest", content="已停用的历史偏好", enabled=True, confirmed=True))
        mr.add(run)
        mr.commit()
        run_id = run.id
    deps = _deps(fclient, llm=FakeLLM(), run_id=run_id)
    from app.morning_report.config import MRSettings

    with fclient.app.state.mr_session_factory() as mr:
        # deps_override 路径跳过索引段；news 通过 collect run 提供
        for n in NEWS:
            from app.morning_report.models import NewsItem
            mr.add(NewsItem(run_id=collect.id, category=n["category"], title=n["title"],
                            summary=n["summary"], source_name=n["source_name"],
                            source_url=n["source_url"], published_at=n["published_at"],
                            content_hash=n["content_hash"], dedupe_status="unique", raw_ref={}))
        mr.commit()
        statements = []
        def capture_sql(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        engine = mr.get_bind()
        event.listen(engine, "before_cursor_execute", capture_sql)
        try:
            out = report_service.run_generate(
                mr, run_id, MRSettings(schedule_enabled=False), mode="manual",
                deps_override=deps, hub_session_factory=None,
                mr_session_factory=fclient.app.state.mr_session_factory)
        finally:
            event.remove(engine, "before_cursor_execute", capture_sql)
        assert not any("memories" in sql.lower() for sql in statements)
    assert out["status"] == "success"
    assert "fact_check" not in out
    with fclient.app.state.mr_session_factory() as mr:
        assert mr.get(RunRecord, run_id).status == "success"
        assert len(mr.execute(select(ReportVersion)).scalars().all()) == 1
