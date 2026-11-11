"""LangGraph 晨报工作流（V0.6 §五 / V0.6.1 §3.2）。

结构：并行(资讯分析, 个人分析) → 并行(技术研究, 目标分析 Subagent) → 建议(后置) → 主编
      → 质量评价(可缺失) → 发布(幂等主报告)。
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
from ..services.cancel import check_cancel
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
        self.progress = None  # ProgressTracker（可选）；节点据此上报阶段状态
        self.cancel_token = None  # CancelToken（可选）；节点入口安全检查点

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
    coverage_notes: list[str]
    memory: list[dict]
    personal: dict              # hub 只读上下文
    news_selection: dict        # 资讯分析输出（缓存）
    personal_summary: str       # 个人分析输出（缓存）
    tech_result: dict           # {status: ok/failed, content}
    goal_result: dict
    advice_result: dict         # {status: ok/failed/no_advice, advices}
    draft: str                  # 主编正文 Markdown
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

def _limit_selection(selection: dict, news: list[dict]) -> dict:
    output = dict(selection)
    for category in ("domestic", "international"):
        pool = {n["id"]: n for n in news if n["category"] == category}
        seen = set()
        chosen = []
        for item in selection.get(category, []):
            if not isinstance(item, dict) or item.get("id") not in pool:
                continue
            source = pool[item["id"]]
            key = (("group", source["event_group_id"]) if source.get("event_group_id") is not None
                   else ("item", source["id"]))
            if key in seen:
                continue
            seen.add(key)
            chosen.append(item)
            if len(chosen) == 10:
                break
        output[category] = chosen
    return output


def node_info_analysis(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("info_analysis")
    fp = stage_cache.fingerprint(
        "news", [{key: n.get(key) for key in (
            "id", "content_hash", "summary", "published_at", "rank", "rank_date",
            "selection_kind", "event_group_id")} for n in state["news"]],
        "memory", [m["updated_at"] for m in state["memory"]],
        deps.prompt_version, deps.llm.model,
    )
    with deps.mr_session_factory() as mr:
        cached = stage_cache.get_cached(mr, "info_analysis", fp)
        if cached is not None:
            deps.progress and deps.progress.stage_completed(
                "info_analysis", summary="命中阶段缓存",
                status="skipped", reason="输入未变化，复用缓存")
            return {"news_selection": _limit_selection(cached, state["news"])}
        memory_txt = "；".join(m["content"] for m in state["memory"] if m.get("enabled"))
        result = deps.llm.chat([{"role": "user", "content": prompts.INFO_ANALYSIS.format(
            news=json.dumps(state["news"], ensure_ascii=False), memory=memory_txt)}], json_mode=True)
        deps.record("info_analysis", result)
        selection = _limit_selection(_json_of(result.content), state["news"])
        stage_cache.put_cache(mr, "info_analysis", fp, selection, model=deps.llm.model,
                              prompt_version=deps.prompt_version)
    deps.progress and deps.progress.stage_completed(
        "info_analysis",
        summary=f"选中 国内{len(selection.get('domestic', []))}/国际{len(selection.get('international', []))}/AI{len(selection.get('ai', []))} 条",
        data={"selected": {k: len(v) for k, v in selection.items()}})
    return {"news_selection": selection}


def node_personal_analysis(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("personal_analysis")
    p = state["personal"]
    fp = stage_cache.fingerprint(
        "personal", p, "memory", [m["updated_at"] for m in state["memory"]],
        deps.prompt_version, deps.llm.model,
    )
    with deps.mr_session_factory() as mr:
        cached = stage_cache.get_cached(mr, "personal_analysis", fp)
        if cached is not None:
            deps.progress and deps.progress.stage_completed(
                "personal_analysis", summary="命中阶段缓存",
                status="skipped", reason="输入未变化，复用缓存")
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
    deps.progress and deps.progress.stage_completed("personal_analysis",
                                                    summary=f"{len(summary)} 字总结")
    return {"personal_summary": summary}


def node_tech_research(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    if not state["news_selection"].get("ai"):
        deps.progress and deps.progress.stage_completed(
            "tech_research", summary="本期无 AI 候选，跳过", status="skipped",
            reason="资讯分析未选出 AI 条目")
        return {"tech_result": {"status": "ok", "content": "本期无值得深究的 AI 进展。"}}
    deps.progress and deps.progress.stage_started("tech_research")
    fp = stage_cache.fingerprint(
        "tech", state["news_selection"]["ai"], deps.prompt_version, deps.llm.model)
    with deps.mr_session_factory() as mr:
        cached = stage_cache.get_cached(mr, "tech_research", fp)
        if cached is not None:
            deps.progress and deps.progress.stage_completed(
                "tech_research", summary="命中阶段缓存", status="skipped",
                reason="输入未变化，复用缓存")
            return {"tech_result": cached}
        try:
            content = deps.subagents.run("tech_research", prompts.TECH_RESEARCH.format(
                ai_items=json.dumps(state["news_selection"]["ai"], ensure_ascii=False)), tools=[])
            res = {"status": "ok", "content": content}
        except Exception as exc:
            logger.warning("技术研究失败，按规则降级: %s", f"{type(exc).__name__}: {exc}"[:150])
            res = {"status": "failed", "content": "", "error": f"{type(exc).__name__}"}
            deps.progress and deps.progress.stage_completed(
                "tech_research", summary="执行失败，结论缺失", status="skipped",
                reason=f"{type(exc).__name__}: 按规则降级，建议不引用该结论")
        else:
            deps.progress and deps.progress.stage_completed(
                "tech_research", summary=f"分析完成（{len(content)} 字）",
                data={"result_chars": len(content)})
        stage_cache.put_cache(mr, "tech_research", fp, res, model=deps.llm.model,
                              prompt_version=deps.prompt_version)
    return {"tech_result": res}


def node_goal_analysis(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("goal_analysis")
    fp = stage_cache.fingerprint(
        "goal", state["personal"], "memory", [m["updated_at"] for m in state["memory"]],
        deps.prompt_version, deps.llm.model)
    with deps.mr_session_factory() as mr:
        cached = stage_cache.get_cached(mr, "goal_analysis", fp)
        if cached is not None:
            deps.progress and deps.progress.stage_completed(
                "goal_analysis", summary="命中阶段缓存", status="skipped",
                reason="输入未变化，复用缓存")
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
            deps.progress and deps.progress.stage_completed(
                "goal_analysis", summary="执行失败，结论缺失", status="skipped",
                reason=f"{type(exc).__name__}: 按规则降级")
        else:
            deps.progress and deps.progress.stage_completed(
                "goal_analysis", summary=f"分析完成（{len(content)} 字）",
                data={"result_chars": len(content)})
        stage_cache.put_cache(mr, "goal_analysis", fp, res, model=deps.llm.model,
                              prompt_version=deps.prompt_version)
    return {"goal_result": res}


def node_advice(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("advice")
    ctx = {
        "news": state["news_selection"],
        "personal": state.get("personal_summary", ""),
        "tech": state["tech_result"],
        "goal": state["goal_result"],
    }
    if state["tech_result"].get("status") == "failed" and state["goal_result"].get("status") == "failed":
        deps.progress and deps.progress.stage_failed("advice", "上游技术研究与目标分析均失败，无法形成建议")
        return {"advice_result": {"status": "failed", "advices": [], "note": "建议分析失败"}}
    result = deps.llm.chat([{"role": "user", "content": prompts.ADVICE.format(
        context=json.dumps(ctx, ensure_ascii=False))}], json_mode=True)
    deps.record("advice", result)
    try:
        data = _json_of(result.content)
        advices = [{"content": a.get("content", ""), "basis": a.get("basis", "")}
                   for a in data.get("advices", [])][:3]
        deps.progress and deps.progress.stage_completed(
            "advice", summary=f"{len(advices)} 条建议",
            data={"advice_count": len(advices)})
        return {"advice_result": {"status": "ok", "advices": advices, "note": data.get("note", "")}}
    except ValueError:
        deps.progress and deps.progress.stage_failed("advice", "建议输出解析失败")
        return {"advice_result": {"status": "failed", "advices": [], "note": "建议输出解析失败"}}


def _selected_with_urls(state: MRState, cat: str) -> list[dict]:
    """把资讯分析选中的条目补上 summary 与 source_url（主编只能用材料内链接）。"""

    sel = state["news_selection"].get(cat) or []
    by_id = {n["id"]: n for n in state["news"]}
    out = []
    for item in sel:
        src_news = by_id.get(item.get("id")) or {}
        out.append({
            "title": item.get("title") or src_news.get("title"),
            "summary": src_news.get("summary", ""),
            "url": src_news.get("source_url", ""),
            "why": item.get("why", ""),
            "value": item.get("value", ""),
        })
    return out


def node_editor(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("editor")
    sel = state["news_selection"]
    result = deps.llm.chat([{"role": "user", "content": prompts.EDITOR.format(
        generated_at=datetime.now(CST).isoformat(timespec="seconds"),
        domestic=json.dumps(_selected_with_urls(state, "domestic"), ensure_ascii=False),
        international=json.dumps(_selected_with_urls(state, "international"), ensure_ascii=False),
        ai=json.dumps(_selected_with_urls(state, "ai"), ensure_ascii=False),
        personal=state.get("personal_summary", ""),
        tech=state["tech_result"].get("content", "") or "（技术研究缺失，本期不作技术深评）",
        goal=state["goal_result"].get("content", "") or "（目标分析缺失）",
        advice=json.dumps(state["advice_result"], ensure_ascii=False),
        coverage="；".join(state.get("coverage_notes", [])) or "无额外覆盖缺口",
    )}])
    deps.record("editor", result)
    deps.progress and deps.progress.stage_completed("editor", summary=f"正文 {len(result.content)} 字")
    draft = result.content.strip()
    notes = state.get("coverage_notes", [])
    if notes:
        draft += "\n\n> 采集说明：" + "；".join(notes)
    return {"draft": draft}


def node_quality_eval(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
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
    check_cancel(deps.cancel_token)
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

def build_workflow(deps: WorkflowDeps):
    g = StateGraph(MRState)
    g.add_node("info_analysis", _async(node_info_analysis, deps))
    g.add_node("personal_analysis", _async(node_personal_analysis, deps))
    g.add_node("tech_research", _async(node_tech_research, deps))
    g.add_node("goal_analysis", _async(node_goal_analysis, deps))
    g.add_node("advice", _async(node_advice, deps))
    g.add_node("editor", _async(node_editor, deps))
    g.add_node("quality_eval", _async(node_quality_eval, deps))
    g.add_node("publish", _async(node_publish, deps))

    g.set_entry_point("info_analysis")
    g.add_edge("__start__", "personal_analysis")
    g.add_edge("info_analysis", "tech_research")
    g.add_edge("personal_analysis", "goal_analysis")
    g.add_edge("tech_research", "advice")
    g.add_edge("goal_analysis", "advice")
    g.add_edge("advice", "editor")
    g.add_edge("editor", "quality_eval")
    g.add_edge("quality_eval", "publish")
    g.add_edge("publish", END)
    return g


def _async(node_fn, deps):
    """同步节点 → 异步包装（独立线程执行，保证并行节点真正并发且不阻塞事件循环）。"""

    async def wrapper(state):
        return await asyncio.to_thread(node_fn, state, deps)

    return wrapper
