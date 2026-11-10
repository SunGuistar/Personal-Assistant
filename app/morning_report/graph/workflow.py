"""LangGraph 晨报工作流（V0.6 §五 / V0.6.1 §3.2）。

结构：并行(资讯分析, 个人分析) → 并行(技术研究, 目标分析 Subagent) → 建议(后置) → 主编
      → 事实校验(阻塞) → 质量评价(可缺失) → 发布(幂等主报告)。
LLM 与 Subagent 经 WorkflowDeps 注入：生产用真实现，测试用假实现（图结构始终真实）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Protocol, TypedDict

from langgraph.graph import END, StateGraph

from ..services import stage_cache
from . import prompts

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


class LlmChat(Protocol):
    """与 ChatClient.chat 同签名，便于注入假实现。"""

    model: str

    def chat(self, messages: list[dict], *, json_mode: bool = False,
             tools: list[dict] | None = None, thinking: bool | None = None): ...


class SubagentRunner(Protocol):
    """技术研究/目标分析/建议的执行器（生产实现见 subagents.py）。"""

    def run(self, name: str, prompt: str, tools: list) -> str: ...


class WorkflowDeps:
    def __init__(self, llm: LlmChat, subagents: SubagentRunner, mr_session_factory,
                 run_id: int, prompt_version: str = prompts.PROMPT_VERSION):
        self.llm = llm
        self.subagents = subagents
        self.mr_session_factory = mr_session_factory
        self.run_id = run_id
        self.prompt_version = prompt_version
        self.recorder = None  # callable(node, result, model, base_url)，生产注入落 TokenUsage

    def record(self, node: str, result) -> None:
        if self.recorder is not None:
            try:
                self.recorder(node, result, getattr(self.llm, "model", ""),
                              getattr(self.llm, "base_url", ""))
            except Exception:
                logger.warning("Token 用量落库失败（不影响主流程）", exc_info=True)


class MRState(TypedDict, total=False):
    run_id: int
    snapshot_id: str
    report_date: str
    window_start: str
    window_end: str
    news: list[dict]            # 本期窗口内新闻（含 category/title/summary/url/published_at）
    clues: list[dict]           # 无可靠时间线索
    memory: list[dict]
    personal: dict              # hub 只读上下文
    news_selection: dict        # 资讯分析输出（缓存）
    personal_summary: str       # 个人分析输出（缓存）
    tech_result: dict           # {status: ok/failed, content}
    goal_result: dict
    advice_result: dict         # {status: ok/failed/no_advice, advices}
    draft: str                  # 主编正文 Markdown
    fact_check: dict            # {ok, issues}
    evaluation: dict            # {status, scores, composite, comment}
    publish: dict               # {version_id, version_no, is_primary}
    degraded: list[str]
    status: str                 # running/success/failed/blocked
    error: str


def _json_of(content: str) -> dict:
    """容忍 ```json 围栏的 JSON 解析；失败抛 ValueError（节点级处理）。"""

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"输出不是 JSON: {content[:80]}")
    return json.loads(text[start:end + 1])


# ---------- 节点 ----------

def node_info_analysis(state: MRState, deps: WorkflowDeps) -> dict:
    fp = stage_cache.fingerprint(
        "news", [n["content_hash"] for n in state["news"]],
        "memory", [m["updated_at"] for m in state["memory"]],
        deps.prompt_version, deps.llm.model,
    )
    with deps.mr_session_factory() as mr:
        cached = stage_cache.get_cached(mr, "info_analysis", fp)
        if cached is not None:
            return {"news_selection": cached}
        memory_txt = "；".join(m["content"] for m in state["memory"] if m.get("enabled"))
        result = deps.llm.chat([{"role": "user", "content": prompts.INFO_ANALYSIS.format(
            news=json.dumps(state["news"], ensure_ascii=False), memory=memory_txt)}], json_mode=True)
        deps.record("info_analysis", result)
        selection = _json_of(result.content)
        stage_cache.put_cache(mr, "info_analysis", fp, selection, model=deps.llm.model,
                              prompt_version=deps.prompt_version)
    return {"news_selection": selection}


def node_personal_analysis(state: MRState, deps: WorkflowDeps) -> dict:
    p = state["personal"]
    fp = stage_cache.fingerprint(
        "personal", p, "memory", [m["updated_at"] for m in state["memory"]],
        deps.prompt_version, deps.llm.model,
    )
    with deps.mr_session_factory() as mr:
        cached = stage_cache.get_cached(mr, "personal_analysis", fp)
        if cached is not None:
            return {"personal_summary": cached["summary"]}
        result = deps.llm.chat([{"role": "user", "content": prompts.PERSONAL_ANALYSIS.format(
            window=f"{state['window_start']} ~ {state['window_end']}",
            done=json.dumps(p.get("daily_done", []), ensure_ascii=False),
            highlight=json.dumps(p.get("longterm_highlight", []), ensure_ascii=False),
            active=json.dumps(p.get("longterm_active", []), ensure_ascii=False),
            infos=json.dumps(p.get("important_infos", []), ensure_ascii=False))}])
        deps.record("personal_analysis", result)
        summary = result.content.strip()
        stage_cache.put_cache(mr, "personal_analysis", fp, {"summary": summary},
                              model=deps.llm.model, prompt_version=deps.prompt_version)
    return {"personal_summary": summary}


def node_tech_research(state: MRState, deps: WorkflowDeps) -> dict:
    if not state["news_selection"].get("ai"):
        return {"tech_result": {"status": "ok", "content": "本期无值得深究的 AI 进展。"}}
    fp = stage_cache.fingerprint(
        "tech", state["news_selection"]["ai"], deps.prompt_version, deps.llm.model)
    with deps.mr_session_factory() as mr:
        cached = stage_cache.get_cached(mr, "tech_research", fp)
        if cached is not None:
            return {"tech_result": cached}
        try:
            content = deps.subagents.run("tech_research", prompts.TECH_RESEARCH.format(
                ai_items=json.dumps(state["news_selection"]["ai"], ensure_ascii=False)), tools=[])
            res = {"status": "ok", "content": content}
        except Exception as exc:
            logger.warning("技术研究失败，按规则降级: %s", f"{type(exc).__name__}: {exc}"[:150])
            res = {"status": "failed", "content": "", "error": f"{type(exc).__name__}"}
        stage_cache.put_cache(mr, "tech_research", fp, res, model=deps.llm.model,
                              prompt_version=deps.prompt_version)
    return {"tech_result": res}


def node_goal_analysis(state: MRState, deps: WorkflowDeps) -> dict:
    fp = stage_cache.fingerprint(
        "goal", state["personal"], "memory", [m["updated_at"] for m in state["memory"]],
        deps.prompt_version, deps.llm.model)
    with deps.mr_session_factory() as mr:
        cached = stage_cache.get_cached(mr, "goal_analysis", fp)
        if cached is not None:
            return {"goal_result": cached}
        try:
            content = deps.subagents.run("goal_analysis", prompts.GOAL_ANALYSIS.format(
                personal=state.get("personal_summary", ""),
                plans=json.dumps(state["personal"].get("longterm_highlight", []), ensure_ascii=False),
                memory="；".join(m["content"] for m in state["memory"] if m.get("enabled")),
            ), tools=[])
            res = {"status": "ok", "content": content}
        except Exception as exc:
            logger.warning("目标分析失败，按规则降级: %s", f"{type(exc).__name__}: {exc}"[:150])
            res = {"status": "failed", "content": "", "error": f"{type(exc).__name__}"}
        stage_cache.put_cache(mr, "goal_analysis", fp, res, model=deps.llm.model,
                              prompt_version=deps.prompt_version)
    return {"goal_result": res}


def node_advice(state: MRState, deps: WorkflowDeps) -> dict:
    ctx = {
        "news": state["news_selection"],
        "personal": state.get("personal_summary", ""),
        "tech": state["tech_result"],
        "goal": state["goal_result"],
    }
    if state["tech_result"].get("status") == "failed" and state["goal_result"].get("status") == "failed":
        return {"advice_result": {"status": "failed", "advices": [], "note": "建议分析失败"}}
    result = deps.llm.chat([{"role": "user", "content": prompts.ADVICE.format(
        context=json.dumps(ctx, ensure_ascii=False))}], json_mode=True)
    deps.record("advice", result)
    try:
        data = _json_of(result.content)
        advices = [{"content": a.get("content", ""), "basis": a.get("basis", "")}
                   for a in data.get("advices", [])][:3]
        return {"advice_result": {"status": "ok", "advices": advices, "note": data.get("note", "")}}
    except ValueError:
        return {"advice_result": {"status": "failed", "advices": [], "note": "建议输出解析失败"}}


def node_editor(state: MRState, deps: WorkflowDeps) -> dict:
    sel = state["news_selection"]
    result = deps.llm.chat([{"role": "user", "content": prompts.EDITOR.format(
        generated_at=datetime.now(CST).isoformat(timespec="seconds"),
        domestic=json.dumps(sel.get("domestic", []), ensure_ascii=False),
        international=json.dumps(sel.get("international", []), ensure_ascii=False),
        ai=json.dumps(sel.get("ai", []), ensure_ascii=False),
        personal=state.get("personal_summary", ""),
        tech=state["tech_result"].get("content", "") or "（技术研究缺失，本期不作技术深评）",
        goal=state["goal_result"].get("content", "") or "（目标分析缺失）",
        advice=json.dumps(state["advice_result"], ensure_ascii=False),
    )}])
    deps.record("editor", result)
    return {"draft": result.content.strip()}


def node_fact_check(state: MRState, deps: WorkflowDeps) -> dict:
    material = json.dumps({
        "news": state["news"], "personal": state["personal"],
    }, ensure_ascii=False)[:6000]
    result = deps.llm.chat([{"role": "user", "content": prompts.FACT_CHECK.format(
        material=material, content=state["draft"])}], json_mode=True)
    deps.record("fact_check", result)
    try:
        check = _json_of(result.content)
    except ValueError:
        check = {"ok": False, "issues": ["事实校验输出无法解析，按不通过处理"]}
    check.setdefault("issues", [])
    # 规则校验：正文中出现的来源链接必须来自本期材料
    urls_in_material = {n.get("source_url") for n in state["news"] if n.get("source_url")}
    import re
    cited = set(re.findall(r"\((https?://[^)]+)\)", state["draft"]))
    orphan = [u for u in cited if u not in urls_in_material]
    if orphan:
        check["issues"].append(f"正文引用了材料外的链接: {orphan[:3]}")
    check["ok"] = bool(check["ok"]) and not orphan
    return {"fact_check": check}


def node_quality_eval(state: MRState, deps: WorkflowDeps) -> dict:
    try:
        result = deps.llm.chat([{"role": "user", "content": prompts.QUALITY_EVAL.format(
            content=state["draft"])}], json_mode=True)
        deps.record("quality_eval", result)
        data = _json_of(result.content)
        scores = data.get("scores") or {}
        valid = {k: max(0, min(100, int(v))) for k, v in scores.items()
                 if isinstance(v, (int, float))}
        if len(valid) < 5:
            raise ValueError("五维分数不完整")
        composite = round(sum(valid.values()) / 5)  # quality_score_v1：等权、四舍五入
        return {"evaluation": {"status": "ok", "scores": valid, "composite": composite,
                               "comment": data.get("comment", "")}}
    except Exception as exc:
        logger.warning("质量评价失败（不阻塞发布）: %s", f"{type(exc).__name__}: {exc}"[:150])
        return {"evaluation": {"status": "failed", "scores": None, "composite": None,
                               "comment": ""}}


def node_publish(state: MRState, deps: WorkflowDeps) -> dict:
    from sqlalchemy import func as sqla_func
    from sqlalchemy import select as sqla_select

    from ..models import Evaluation, ReportVersion

    with deps.mr_session_factory() as mr:
        existing = mr.execute(
            sqla_select(sqla_func.max(ReportVersion.version_no))
            .where(ReportVersion.report_date == state["report_date"])
        ).scalar() or 0
        primary_exists = mr.execute(
            sqla_select(ReportVersion.id)
            .where(ReportVersion.report_date == state["report_date"],
                   ReportVersion.is_primary.is_(True))
            .limit(1)
        ).first() is not None
        ver = ReportVersion(
            run_id=state["run_id"], report_date=state["report_date"],
            version_no=existing + 1, is_primary=not primary_exists,
            status="published", title=f"今日晨报 {state['report_date']}",
            sections={
                "news_selection": state["news_selection"],
                "personal_summary": state.get("personal_summary", ""),
                "tech": state["tech_result"], "goal": state["goal_result"],
                "advice": state["advice_result"],
            },
            content_md=state["draft"],
            window_start=state["window_start"], window_end=state["window_end"],
            snapshot_id=state["snapshot_id"],
            fact_check=state["fact_check"],
        )
        mr.add(ver)
        mr.flush()
        ev = state.get("evaluation") or {}
        mr.add(Evaluation(
            version_id=ver.id, status=ev.get("status", "failed"),
            scores=ev.get("scores"), composite=ev.get("composite"),
            comment=ev.get("comment", ""), model=getattr(deps.llm, "model", ""),
            rule_version="quality_score_v1",
        ))
        mr.commit()
        return {"publish": {"version_id": ver.id, "version_no": ver.version_no,
                            "is_primary": ver.is_primary}}


# ---------- 图装配 ----------

def route_after_fact_check(state: MRState) -> str:
    if state.get("fact_check", {}).get("ok"):
        return "quality_eval"
    return "blocked"


def build_workflow(deps: WorkflowDeps):
    g = StateGraph(MRState)
    g.add_node("info_analysis", _async(node_info_analysis, deps))
    g.add_node("personal_analysis", _async(node_personal_analysis, deps))
    g.add_node("tech_research", _async(node_tech_research, deps))
    g.add_node("goal_analysis", _async(node_goal_analysis, deps))
    g.add_node("advice", _async(node_advice, deps))
    g.add_node("editor", _async(node_editor, deps))
    g.add_node("fact_check", _async(node_fact_check, deps))
    g.add_node("quality_eval", _async(node_quality_eval, deps))
    g.add_node("publish", _async(node_publish, deps))

    g.set_entry_point("info_analysis")
    g.add_edge("__start__", "personal_analysis")
    g.add_edge("info_analysis", "tech_research")
    g.add_edge("personal_analysis", "goal_analysis")
    g.add_edge("tech_research", "advice")
    g.add_edge("goal_analysis", "advice")
    g.add_edge("advice", "editor")
    g.add_edge("editor", "fact_check")
    g.add_conditional_edges("fact_check", route_after_fact_check,
                            {"quality_eval": "quality_eval", "blocked": END})
    g.add_edge("quality_eval", "publish")
    g.add_edge("publish", END)
    return g


def _async(node_fn, deps):
    """同步节点 → 异步包装（独立线程执行，保证并行节点真正并发且不阻塞事件循环）。"""

    async def wrapper(state):
        return await asyncio.to_thread(node_fn, state, deps)

    return wrapper
