"""LangGraph 晨报工作流（V0.6 §五 / V0.6.1 §3.2）。

结构：新闻整理 → 个人上下文 → GoalAnalysis → ActionSuggest → 主编
      → 发布(幂等主报告)。
LLM 与 Subagent 经 WorkflowDeps 注入：生产用真实现，测试用假实现（图结构始终真实）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Protocol, TypedDict
from urllib.parse import quote, urlsplit

from langgraph.graph import END, StateGraph

from ..services import stage_cache
from ..services.cancel import check_cancel
from . import prompts

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


class LlmChat(Protocol):
    """与 ChatClient.chat 同签名，便于注入假实现。"""

    model: str

    def chat(self, messages: list[dict], *, json_mode: bool = True,
             tools: list[dict] | None = None, thinking: bool | None = None): ...


class SubagentRunner(Protocol):
    """目标分析与行动建议的执行器（生产实现见 subagents.py）。"""

    def run(self, name: str, prompt: str, tools: list) -> str: ...


class WorkflowDeps:
    def __init__(self, llm: LlmChat | None, subagents: SubagentRunner, mr_session_factory,
                 run_id: int, prompt_version: str = prompts.PROMPT_VERSION):
        self.llm = llm
        self.subagents = subagents
        self.mr_session_factory = mr_session_factory
        self.run_id = run_id
        self.prompt_version = prompt_version
        self.recorder = None  # callable(node, result, model, base_url)，生产注入落 TokenUsage
        self.progress = None  # ProgressTracker（可选）；节点据此上报阶段状态
        self.cancel_token = None  # CancelToken（可选）；节点入口安全检查点

    def record(self, node: str, result, client=None) -> None:
        if self.recorder is not None:
            try:
                client = client or self.llm
                self.recorder(node, result, getattr(client, "model", ""),
                              getattr(client, "base_url", ""))
            except Exception:
                logger.warning("Token 用量落库失败（不影响主流程）", exc_info=True)


class MRState(TypedDict, total=False):
    run_id: int
    snapshot_id: str
    report_date: str
    generation_mode: str
    window_start: str
    window_end: str
    news: list[dict]            # 本期采集的官方榜单新闻（不含 AI；AI 走 ai_daily 确定性组装）
    clues: list[dict]           # 无可靠时间线索
    ai_daily: list[dict]        # 当期 AIHOT 日报完整条目（去重后、按 display_order；不参与模型筛选）
    news_errors: dict[str, str]
    coverage_notes: list[str]
    personal: dict              # hub 只读上下文
    news_selection: dict        # 资讯分析输出（缓存）
    personal_summary: str       # 个人分析输出（缓存）
    goal_result: dict
    advice_result: dict         # {status: ok/failed/no_advice, advices}
    draft: str                  # 主编正文 Markdown
    publish: dict               # {version_id, version_no, is_primary}
    degraded: list[str]
    status: str                 # running/success/failed/blocked
    error: str


def _json_of(content: str) -> dict:
    """严格解析 JSON 对象；不接受 Markdown 围栏或夹带的说明文字。"""
    from ..services.json_contract import parse_json_object
    return parse_json_object(content)


# ---------- AI 日报列表：确定性组装与占位符注入 ----------

AI_LIST_PLACEHOLDER = "{{AI_NEWS_LIST}}"
_MD_TITLE_ESCAPE = re.compile(r"([\\`*_\[\]])")
_AI_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*AI[^\n]*$")
_ANY_HEADING_RE = re.compile(r"(?m)^#{1,6}\s")
_SECTION3_RE = re.compile(r"(?m)^#{1,6}\s*三[、.．]")
_LIST_LINE_RE = re.compile(r"^\s*(?:[-*+]|\d+[.、)])\s+")


def _md_escape_title(title: str) -> str:
    """标题中的 Markdown 特殊字符转义（破坏链接语法的括号优先）。"""

    return _MD_TITLE_ESCAPE.sub(r"\\\1", title)


def _safe_url(url) -> str:
    """只接受有效 http/https；空白与括号百分号编码，防破坏 Markdown 链接；其余丢弃。"""

    if not isinstance(url, str) or not url.strip():
        return ""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    return quote(url, safe=":/?#[]@!$&'*+,;=%~")


def assemble_ai_list(items: list[dict]) -> str:
    """把当期 AIHOT 日报条目组装为 Markdown 列表（全部去重后标题+链接，顺序=日报展示顺序）。"""

    lines = []
    for it in items:
        title = _md_escape_title(str(it.get("title") or "").strip()) or "（无标题）"
        url = _safe_url(it.get("url") or it.get("source_url") or "")
        lines.append(f"- [{title}]({url})" if url else f"- {title}")
    return "\n".join(lines) if lines else "（本期 AIHOT 日报不可用或无条目，AI 资讯列表缺失）"


def _strip_model_ai_items(head: str) -> str:
    """占位符之前、最近一个 AI 小节标题之后：剔除模型自写的列表行（防虚构/改写），保留引语。"""

    lines = head.split("\n")
    ai_idx = None
    for i, line in enumerate(lines):
        if _AI_HEADING_RE.match(line.rstrip()):
            ai_idx = i
    if ai_idx is None:
        return head
    kept = [line for line in lines[ai_idx + 1:] if not _LIST_LINE_RE.match(line)]
    return "\n".join(lines[:ai_idx + 1] + kept).rstrip() + "\n"


def inject_ai_list(draft: str, block: str) -> tuple[str, bool]:
    """把组装好的 AI 列表注入正文。返回 (正文, 是否按占位符注入)。

    占位符在则替换首个、清除重复占位，并剔除占位符前模型自写的 AI 列表行；
    模型遗漏占位符时改写已有 AI 小节内容，无小节则插入到"三、"标题之前，
    仍找不到则追加到文末——不做脆弱的全文替换，不产生重复小节。
    """

    if AI_LIST_PLACEHOLDER in draft:
        first = draft.index(AI_LIST_PLACEHOLDER)
        out = _strip_model_ai_items(draft[:first]) + block + draft[first + len(AI_LIST_PLACEHOLDER):]
        return out.replace(AI_LIST_PLACEHOLDER, ""), True
    m = _AI_HEADING_RE.search(draft)
    if m:
        nxt = _ANY_HEADING_RE.search(draft, m.end())
        end = nxt.start() if nxt else len(draft)
        return draft[:m.end()] + "\n\n" + block + "\n\n" + draft[end:].lstrip("\n"), False
    m3 = _SECTION3_RE.search(draft)
    if m3:
        return draft[:m3.start()].rstrip() + "\n\n### AI\n\n" + block + "\n\n" + draft[m3.start():], False
    return draft.rstrip() + "\n\n### AI\n\n" + block, False


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
    """只按来源顺序整理新闻，不进行模型二次筛选；AIHOT 保持完整。"""
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("info_analysis")
    selected = {}
    for category in ("domestic", "international"):
        rows = [n for n in state["news"] if n.get("category") == category]
        rows.sort(key=lambda n: (n.get("rank") or 10**9, n["id"]))
        selected[category] = [{"id": n["id"], "title": n["title"]} for n in rows]
    selected = _limit_selection(selected, state["news"])
    selected["ai"] = list(state.get("ai_daily", []))
    deps.progress and deps.progress.stage_completed("info_analysis", status="warning" if state.get("news_errors") else "success",
        reason="；".join(state.get("news_errors", {}).values()), summary="新闻按来源顺序整理，无模型筛选",
        data={"selected": {k: len(v) for k, v in selected.items()}})
    return {"news_selection": selected}


def node_personal_analysis(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("personal_analysis")
    p = state["personal"]
    counts = {key: len(value) for key, value in p.items() if isinstance(value, list)}
    summary = (f"系统取得窗口内完成任务 {counts.get('daily_done', 0)} 条、昨日未完成 {counts.get('yesterday_pending', 0)} 条、"
               f"今日待办 {counts.get('today_pending', 0)} 条。未记录不能推断为未发生或没有进展。")
    deps.progress and deps.progress.stage_completed("personal_analysis", summary="个人上下文准备完成",
        data={"counts": counts, "source_id": p.get("source_meta", {}).get("source_id"),
              "source_status": p.get("source_meta", {}).get("status", "injected")})
    return {"personal_summary": summary}


def _decision_context(state):
    personal = dict(state.get("personal", {}))
    if "source_meta" in personal:
        personal["source_meta"] = {k: v for k, v in personal["source_meta"].items() if k != "database_path"}
    return {"personal": personal, "goal_analysis": state.get("goal_result"),
            "window_start": state["window_start"], "window_end": state["window_end"]}


def _evidence(state, deps, stage):
    from ..services.decision_tools import evidence_records
    records = evidence_records(state.get("personal", {}))
    for record in getattr(deps.subagents, "evidence", {}).get(stage, []):
        if record.get("source_id") in records:
            records[record["source_id"]] = record
    return records


def _agent_tools(deps, name):
    factory = getattr(deps.subagents, "tools_for", None)
    return factory(name) if factory else []


def node_goal_analysis(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("goal_analysis")
    try:
        content = deps.subagents.run("goal_analysis", prompts.GOAL_ANALYSIS.format(
            context=json.dumps(_decision_context(state), ensure_ascii=False)), tools=_agent_tools(deps, "goal_analysis"))
        data = _json_of(content)
        records = _evidence(state, deps, "goal_analysis")
        gaps = list(data.get("data_gaps") or [])
        for field in ("current_state", "progress", "risks", "goal_observations", "associations", "questions"):
            values = [data.get(field)] if field == "current_state" else data.get(field, [])
            if not isinstance(values, list):
                raise ValueError("invalid goal schema")
            cleaned = []
            for value in values:
                if not isinstance(value, dict):
                    continue
                refs = value.get("evidence_ids") or []
                if value.get("kind") not in ("confirmed", "analysis", "unknown") or not refs or any(ref not in records for ref in refs):
                    value = {"content": value.get("content", ""), "kind": "unknown", "evidence_ids": []}
                    gaps.append("部分判断缺少有效来源，标为尚未证实")
                cleaned.append(value)
            data[field] = (cleaned[0] if cleaned else {"content": "系统尚未取得足够证据", "kind": "unknown", "evidence_ids": []}) if field == "current_state" else cleaned
        if not any(key.startswith(("daily_tasks:", "long_term_plans:", "important_infos:", "memos:")) for key in records):
            data["current_state"] = {"content": "系统未取得相关个人记录，无法判断实际进展；不代表没有发生或没有进展", "kind": "unknown", "evidence_ids": []}
            gaps.append("个人数据缺失")
        data["data_gaps"] = list(dict.fromkeys(gaps))
        from ..services.report_assembly import validate_yesterday
        yesterday_error = None
        if "yesterday_report" in data:
            data["yesterday_report"] = validate_yesterday(data["yesterday_report"], records)
        else:
            yesterday_error = "目标分析未返回我的昨日内容"

        result = {"status": "ok", "analysis": data, "content": json.dumps(data, ensure_ascii=False)}
        if yesterday_error:
            result["yesterday_error"] = yesterday_error
    except Exception as exc:
        from ..services.cancel import GenerationCancelled
        if isinstance(exc, GenerationCancelled):
            raise
        result = {"status": "failed", "analysis": {}, "content": "系统未能取得目标分析，不能据此判断个人进展", "error": type(exc).__name__}
    deps.progress and deps.progress.stage_completed("goal_analysis", status="success" if result["status"] == "ok" else "skipped",
        summary="个人目标分析完成" if result["status"] == "ok" else "目标分析失败，已明确降级",
        reason=result.get("error", ""),
        data={"tool_calls": getattr(deps.subagents, "last_tool_calls", {}).get("goal_analysis", 0)})
    return {"goal_result": result}


def node_advice(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("advice")
    try:
        content = deps.subagents.run("advice", prompts.ADVICE.format(
            context=json.dumps(_decision_context(state), ensure_ascii=False)), tools=_agent_tools(deps, "advice"))
        data = _json_of(content)
        records = _evidence(state, deps, "advice")
        personal_ids = {key for key in records if key.startswith(("daily_tasks:", "long_term_plans:", "important_infos:", "memos:"))}
        kept, rejected, seen = [], 0, set()
        for item in data.get("advices", []):
            refs = item.get("personal_refs") or []
            evidence = item.get("evidence_ids") or []
            if (not item.get("content") or not item.get("basis") or not item.get("next_step") or not refs or
                any(ref not in personal_ids for ref in refs) or not evidence or any(ref not in records for ref in evidence) or
                item.get("priority") not in ("今日优先", "近期推进", "长期关注")):
                rejected += 1
                continue
            key = (tuple(sorted(refs)), re.sub(r"\s+", "", item["next_step"]).casefold())
            if key in seen:
                rejected += 1
                continue
            seen.add(key)
            if all(records[ref].get("done") or records[ref].get("status") == "completed" for ref in refs):
                rejected += 1
                continue
            item["estimated_time"] = item.get("estimated_time") if item.get("time_basis") else None
            item["expected_value"] = item.get("expected_value") if item.get("value_basis") else None
            kept.append(item)
        result = {"status": "ok", "advices": kept[:3], "note": data.get("note", ""), "rejected_count": rejected}
        if rejected:
            result["note"] += "；部分候选缺少有效个人依据或已完成，未作为行动建议发布"
    except Exception as exc:
        from ..services.cancel import GenerationCancelled
        if isinstance(exc, GenerationCancelled):
            raise
        result = {"status": "failed", "advices": [], "note": "行动建议生成失败，未编造建议", "error": type(exc).__name__}
    deps.progress and deps.progress.stage_completed("advice", status="success" if result["status"] == "ok" else "skipped",
        summary=f"有效行动建议 {len(result['advices'])} 条",
        reason=result.get("error", ""),
        data={"advice_count": len(result["advices"]), "rejected_count": result.get("rejected_count", 0),
              "tool_calls": getattr(deps.subagents, "last_tool_calls", {}).get("advice", 0)})
    return {"advice_result": result}


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


def _source_news_block(state, category):
    rows = _selected_with_urls(state, category)
    pool = {n["id"]: n for n in state["news"]}
    selected = state["news_selection"].get(category, [])
    lines = []
    for item, selected_item in zip(rows, selected):
        source = pool.get(selected_item["id"], {})
        title = _md_escape_title(source.get("title") or item["title"])
        link = _safe_url(source.get("source_url", ""))
        summary = source.get("summary") or "（来源未提供可用摘要，未补写）"
        if len(summary) > 240:
            summary = summary[:240] + "…（来源摘录）"
        lines.append(f"- **[{title}]({link})**\n  {summary}\n  发布时间：{source.get('published_at') or '未知'} · 来源：中国新闻网")
    error = state.get("news_errors", {}).get(category)
    if error:
        lines.insert(0, "资讯暂缺：" + error)
    return "\n\n".join(lines) or "（本期没有可用的官方热点新闻，不补造）"


def _inject_source_news(draft, category, label, block):
    placeholder = "{{" + category.upper() + "_NEWS_LIST}}"
    heading = re.search(r"(?m)^#{2,6}\s*" + label + r"\s*$", draft)
    if heading:
        nxt = _ANY_HEADING_RE.search(draft, heading.end())
        stop = nxt.start() if nxt else len(draft)
        return (draft[:heading.end()] + "\n\n" + block + "\n\n" + draft[stop:]).replace(placeholder, "")
    if placeholder in draft:
        return draft.replace(placeholder, block, 1).replace(placeholder, "")
    anchor = _AI_HEADING_RE.search(draft) or _SECTION3_RE.search(draft)
    pos = anchor.start() if anchor else len(draft)
    return draft[:pos] + f"\n\n### {label}\n\n" + block + "\n\n" + draft[pos:]



def assemble_overview(state: MRState) -> str:
    """指定顺序取来源条目，不调用模型改写标题/摘要。观点类兼容来源历史标签。"""
    chosen = []
    pool = {n["id"]: n for n in state.get("news", [])}
    for category, label in (("domestic", "国内新闻"), ("international", "国外新闻")):
        rows = state.get("news_selection", {}).get(category, [])
        if rows and rows[0].get("id") in pool:
            chosen.append((pool[rows[0]["id"]], label))
    daily = state.get("ai_daily", [])
    if daily:
        chosen.append((daily[0], "AI新闻"))
    chosen.extend((item, "技巧与观点") for item in daily
                  if item.get("section_label") in ("技巧与观点", "讨论与观点"))
    lines = []
    seen = set()
    for item, label in chosen:
        url = _safe_url(item.get("url") or item.get("source_url") or "")
        key = (url or str(item.get("id") or item.get("title")), label)
        if key in seen:
            continue
        seen.add(key)
        title = _md_escape_title(str(item.get("title") or "（无标题）"))
        title = f"[{title}]({url})" if url else title
        summary = str(item.get("summary") or "暂无来源摘要").strip().replace("\n", " ").replace("\r", " ")
        lines.append(f"- {title}【{label}】\n  {summary}")
    return "\n\n".join(lines) or "（本期暂无可用速览资讯）"


def inject_overview(draft: str, block: str) -> str:
    heading = re.search(r"(?m)^(#{1,3})\s*(?:一[、.．]\s*)?开篇速览\s*$", draft)
    if heading:
        next_heading = re.search(r"(?m)^#{1," + str(len(heading[1])) + r"}\s+", draft[heading.end():])
        end = heading.end() + next_heading.start() if next_heading else len(draft)
        draft = draft[:heading.end()] + "\n\n" + block + "\n\n" + draft[end:]
    elif "{{OVERVIEW_LIST}}" in draft:
        draft = draft.replace("{{OVERVIEW_LIST}}", block, 1)
    else:
        anchor = re.search(r"(?m)^#{1,3}\s*二[、.．]", draft)
        pos = anchor.start() if anchor else 0
        draft = draft[:pos] + "## 一、开篇速览\n\n" + block + "\n\n" + draft[pos:]
    return draft.replace("{{OVERVIEW_LIST}}", "")

def node_editor(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("editor")
    from ..services.report_assembly import personal_sections
    goal = state.get("goal_result", {})
    if state.get("yesterday_content"):
        goal = {"status": "ok", "analysis": {"yesterday_report": state["yesterday_content"]}}
    yesterday, advice = personal_sections(state.get("personal", {}), goal, state.get("advice_result", {}))
    ai_block = assemble_ai_list(state.get("ai_daily", []))
    if state.get("news_errors", {}).get("ai"):
        ai_block = "资讯暂缺：" + state["news_errors"]["ai"] + ("\n\n" + ai_block if state.get("ai_daily") else "")
    generated_at = datetime.now(CST).isoformat(timespec="seconds")
    information = "内容窗口：" + str(state.get("window_start", "")) + " ~ " + str(state.get("window_end", "")) + "。\n\n来源：中新网官方热点排行、AIHOT 当期日报与本轮个人记录。\n\n生成时间：" + generated_at
    notes = list(dict.fromkeys(state.get("coverage_notes", [])))
    if notes:
        information += "\n\n采集说明：" + "；".join(notes)
    draft = "\n\n".join([
        "# 今日晨报：" + str(state.get("report_date", "")),
        "## 一、开篇速览", assemble_overview(state),
        "## 二、重要资讯", "### 国内", _source_news_block(state, "domestic"),
        "### 国际", _source_news_block(state, "international"), "### AI", ai_block,
        "## 三、我的昨日", yesterday, "## 四、今日建议", advice, "## 五、信息说明", information,
    ])
    deps.progress and deps.progress.stage_completed(
        "editor", summary=f"程序组装正文 {len(draft)} 字，不调用模型",
        data={"ai_list_items": len(state.get("ai_daily", [])), "llm_calls": 0})
    return {"draft": draft}


def node_publish(state: MRState, deps: WorkflowDeps) -> dict:
    check_cancel(deps.cancel_token)
    deps.progress and deps.progress.stage_started("publish")
    from sqlalchemy import func as sqla_func
    from sqlalchemy import select as sqla_select

    from ..models import ReportVersion
    from ..services.report_news_content import build_news_content
    from ..services.report_assembly import build_yesterday

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
                "news_content": build_news_content(state["news_selection"],
                    state.get("news", []) + state.get("ai_daily", []), state.get("news_errors", {})),
                "yesterday_content": state.get("yesterday_content") or build_yesterday(state.get("personal", {}), state.get("goal_result", {})),
                "assembly_input": {key: state.get(key, [] if key in ("news", "ai_daily", "coverage_notes") else {})
                    for key in ("news", "ai_daily", "coverage_notes", "news_errors")},
                "assembly_personal": {"daily_done": state.get("personal", {}).get("daily_done", [])},
                "personal_summary": state.get("personal_summary", ""),
                "goal": state["goal_result"],
                "advice": state["advice_result"],
            },
            content_md=state["draft"],
            window_start=state["window_start"], window_end=state["window_end"],
            snapshot_id=state["snapshot_id"],
            generation_mode=state.get("generation_mode", "manual"),
        )
        mr.add(ver)
        mr.flush()
        mr.commit()
        return {"publish": {"version_id": ver.id, "version_no": ver.version_no,
                            "is_primary": ver.is_primary}}


# ---------- 图装配 ----------

def build_workflow(deps: WorkflowDeps):
    g = StateGraph(MRState)
    g.add_node("info_analysis", _async(node_info_analysis, deps))
    g.add_node("personal_analysis", _async(node_personal_analysis, deps))
    g.add_node("goal_analysis", _async(node_goal_analysis, deps))
    g.add_node("advice", _async(node_advice, deps))
    g.add_node("editor", _async(node_editor, deps))
    g.add_node("publish", _async(node_publish, deps))

    g.set_entry_point("info_analysis")
    g.add_edge("info_analysis", "personal_analysis")
    g.add_edge("personal_analysis", "goal_analysis")
    g.add_edge("goal_analysis", "advice")
    g.add_edge("advice", "editor")
    g.add_edge("editor", "publish")
    g.add_edge("publish", END)
    return g


def _async(node_fn, deps):
    """同步节点 → 异步包装（独立线程执行，保证并行节点真正并发且不阻塞事件循环）。"""

    async def wrapper(state):
        return await asyncio.to_thread(node_fn, state, deps)

    return wrapper
