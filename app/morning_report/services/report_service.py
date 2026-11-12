"""生成编排（每天 08:30 流程 / 手动重新生成共用）。

步骤（V0.6 §五）：清阶段缓存 → 采集(缺则补)
→ 准备本轮数据 → LangGraph 工作流 → 结果落库。
两个分析 Subagent 使用配置的 DashScope 模型；主编仅程序组装，不创建模型客户端。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters.embedding import DefaultEmbeddingProvider
from ..config import MRSettings
from ..models import NewsItem, RunRecord
from ..services import news_pipeline, progress as progress_mod, stage_cache
from ..services.cancel import GenerationCancelled, check_cancel
from ..services.llm_router import ModelNotAllowedError
from ..services.qdrant_store import QdrantStore
from ..graph.subagents import LangChainSubagentRunner
from ..graph.workflow import WorkflowDeps, build_workflow

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(CST).isoformat()


def log_run(mr: Session, run_id: int, stage: str, message: str,
            level: str = "info", detail: dict | None = None) -> None:
    from ..models import RunLog

    mr.add(RunLog(run_id=run_id, stage=stage, level=level, message=message[:500], detail=detail))
    mr.commit()


def _latest_collect(mr: Session, report_date: str) -> RunRecord | None:
    return mr.execute(
        select(RunRecord)
        .where(RunRecord.run_date == report_date, RunRecord.kind == "collect")
        .order_by(RunRecord.id.desc())
    ).scalars().first()


def run_generate(mr: Session, run_id: int, settings: MRSettings,
                 *, mode: str = "auto", deps_override: WorkflowDeps | None = None,
                 store: QdrantStore | None = None,
                 provider=None, hub_session_factory=None, mr_session_factory=None,
                 clear_cache: bool | None = None, personal_ctx_override: dict | None = None,
                 cancel_token=None) -> dict:
    """执行一期生成。deps_override 仅供测试注入（此时 LLM 无真实调用）。
    cancel_token：协作式取消令牌（Runner 注册）；检查点处抛 GenerationCancelled。

    缓存清理：auto（每天 08:30 新一轮）默认清理；manual 默认复用；clear_cache 显式覆盖
    （manual+full 重算时由 API 传 True）。
    """

    if clear_cache is None:
        clear_cache = mode == "auto"
    run = mr.get(RunRecord, run_id)
    run.status = "running"
    run.started_at = _now()
    mr.commit()
    tracker = progress_mod.ProgressTracker(
        mr_session_factory if mr_session_factory is not None else mr, run_id)
    check_cancel(cancel_token)
    tracker.stage_started("collect")
    if clear_cache:
        log_run(mr, run_id, "generate", f"开始生成（mode={mode}），清理上一轮阶段缓存")
        cleared = stage_cache.clear_all(mr)
        log_run(mr, run_id, "generate", f"阶段缓存已清理 {cleared} 条")
    else:
        log_run(mr, run_id, "generate", f"开始生成（mode={mode}，复用有效阶段缓存）")

    # 1) 采集（缺则补采）
    collect = _latest_collect(mr, run.run_date)
    if (collect is None or collect.status not in ("success", "degraded") or
            news_pipeline.collection_needs_refresh(mr, collect.id) or
            deps_override is None and not news_pipeline.collection_is_current(mr, collect.id)):
        log_run(mr, run_id, "generate", "本期采集不存在、资讯缺失或策略已更新，执行采集", level="warning")
        collect = news_pipeline.create_collect_run(mr, run.run_date)
        try:
            news_pipeline.run_collect(mr, collect.id, cancel_token=cancel_token)
        except GenerationCancelled:
            collect.status = "cancelled"
            collect.stop_reason = "用户主动停止"
            collect.finished_at = collect.stopped_at = _now()
            progress_mod.ProgressTracker(mr, collect.id).stage_completed(
                "collect", status="cancelled", reason="用户主动停止")
            mr.commit()
            raise
        collect = mr.get(RunRecord, collect.id)
        c_rows = mr.execute(select(NewsItem).where(NewsItem.run_id == collect.id)).scalars().all()
        tracker.stage_completed("collect",
                                summary=f"补采完成，{len(c_rows)} 条",
                                data={"saved": len(c_rows), "collect_run_id": collect.id,
                                      "by_category": news_pipeline.saved_category_counts(mr, collect.id)})
    else:
        c_rows_n = mr.execute(select(func.count()).select_from(NewsItem).where(
            NewsItem.run_id == collect.id)).scalar() or 0
        tracker.stage_completed("collect",
                                summary=f"复用本期采集（{c_rows_n} 条）",
                                status="skipped", reason="使用已完成的采集结果",
                                data={"saved": c_rows_n, "collect_run_id": collect.id,
                                      "by_category": news_pipeline.saved_category_counts(mr, collect.id)})

    collect_detail = news_pipeline.collection_summary(mr, collect.id)
    if collect_detail:
        tracker.stage_progress("collect", data={key: collect_detail[key] for key in (
            "per_source", "raw_by_category", "windowed_by_category", "duplicates_merged",
            "coverage_notes", "collection_strategy") if key in collect_detail})
    news_errors = news_pipeline.category_errors(collect_detail, news_pipeline.saved_category_counts(mr, collect.id))
    if news_errors:
        tracker.stage_completed("collect", status="warning", summary="部分资讯缺失，继续生成",
            reason="；".join(news_errors.values()), data={"category_errors": news_errors,
            "source_failures": collect_detail.get("source_failures", {})})

    check_cancel(cancel_token)
    # 3) 准备本轮数据（固定输入，保留现有证据保存逻辑）
    tracker.stage_started("snapshot")
    news_rows = mr.execute(select(NewsItem).where(NewsItem.run_id == collect.id)).scalars().all()
    # 当期 AIHOT 日报成员：按日报归属与展示顺序确定性组装，不走窗口过滤/模型筛选/AI 截断
    daily_rows = [r for r in news_rows
                  if r.category == "ai" and (r.raw_ref or {}).get("daily_member")
                  and (r.raw_ref or {}).get("daily_date") == run.run_date]
    daily_rows.sort(key=lambda r: (r.raw_ref or {}).get("display_order", 10**9))
    ai_daily = [{"id": r.id, "title": r.title, "summary": r.summary or "",
                 "source_name": r.source_name, "url": r.source_url,
                 "section_label": (r.raw_ref or {}).get("section_label", ""),
                 "daily_kind": (r.raw_ref or {}).get("daily_kind", ""),
                 "published_at": r.published_at} for r in daily_rows]
    # 其余 AI 条目（旧策略遗留/线索）不进模型输入：AI 列表唯一来源是当期日报
    news = [{
        "id": r.id, "category": r.category, "title": r.title, "summary": r.summary or "",
        "source_name": r.source_name, "source_url": r.source_url,
        "published_at": r.published_at, "content_hash": r.content_hash,
        "event_group_id": r.event_group_id,
        "selection_kind": (r.raw_ref or {}).get("selection_kind"),
        "rank": (r.raw_ref or {}).get("rank"),
        "rank_date": (r.raw_ref or {}).get("rank_date"),
    } for r in news_rows if r.category != "ai"]
    clues = []  # 国内/国际榜单条目不再按发布时间或时间缺失降为线索
    news = _trim_for_llm(news)
    coverage_notes = list(collect_detail.get("coverage_notes") or ([collect.error] if collect.error else []))
    coverage_notes.extend(reason for reason in news_errors.values() if reason not in coverage_notes)
    snapshot_id = "snap-" + hashlib.sha1(json.dumps(
        [collect.id, len(news), len(ai_daily)],
        ensure_ascii=False).encode()).hexdigest()[:16]
    log_run(mr, run_id, "snapshot", f"快照已冻结: {snapshot_id}",
            detail={"news": len(news), "ai_daily": len(ai_daily)})
    tracker.stage_completed("snapshot", summary=f"快照 {snapshot_id}",
                            data={"news": len(news), "ai_daily": len(ai_daily)})

    # 4) 工作流
    if personal_ctx_override is not None:
        personal_ctx = personal_ctx_override
    elif deps_override is not None:
        personal_ctx = _load_personal(hub_session_factory, collect.window_start, collect.window_end)
    else:
        from .hub_readonly import load_readonly_context
        try:
            personal_ctx = load_readonly_context(settings.personal_db_path, collect.window_start, collect.window_end)
        except (OSError, ValueError, sqlite3.Error) as exc:
            personal_ctx = _load_personal(None, collect.window_start, collect.window_end)
            personal_ctx["source_meta"] = {"status": "failed", "readonly": True, "counts": {},
                "source_id": hashlib.sha256(str(Path(settings.personal_db_path).resolve()).casefold().encode()).hexdigest()[:16],
                "queried_at": _now(), "query_error": type(exc).__name__}
            coverage_notes.append("个人数据库读取失败，系统未取得数据，不能推断为没有进展")
    table_map = {"daily_done": "daily_tasks", "daily_pending": "daily_tasks", "yesterday_pending": "daily_tasks",
                 "today_pending": "daily_tasks", "history_tasks": "daily_tasks", "longterm_highlight": "long_term_plans",
                 "longterm_active": "long_term_plans", "important_infos": "important_infos", "memos": "memos"}
    for key, table in table_map.items():
        for row in personal_ctx.get(key, []):
            if row.get("id") is not None:
                row.setdefault("source_id", f"{table}:{row['id']}")
    meta = personal_ctx.get("source_meta", {})
    log_run(mr, run_id, "personal_context", "个人数据读取完成" if meta.get("status") != "failed" else "个人数据读取失败",
        detail={"source_id": meta.get("source_id"), "counts": meta.get("counts", {}),
                "queried_at": meta.get("queried_at"), "status": meta.get("status", "injected"),
                "missing_tables": meta.get("missing_tables", []), "query_error": meta.get("query_error")})
    _snapshot_personal(mr, run_id, snapshot_id, personal_ctx)
    if deps_override is not None:
        deps = deps_override
    else:
        if mr_session_factory is None:
            raise RuntimeError("生产路径必须注入 mr_session_factory")
        def _recorder(node, result, model, base_url):
            from ..services.llm_router import record_usage as _ru
            with mr_session_factory() as s:
                _ru(s, run_id, node, _ClientShim(model, base_url), result,
                    allowed="dev")
        subagents = LangChainSubagentRunner(settings)
        deps = WorkflowDeps(llm=None, subagents=subagents,
                            mr_session_factory=mr_session_factory, run_id=run_id)
        deps.recorder = _recorder
        subagents.recorder = _recorder
        subagents.configure_context(personal_ctx, tracker, cancel_token)
        log_run(mr, run_id, "generate", f"分析 Subagent 模型: {settings.dashscope_model}；主编程序组装，不调用模型")

    initial = {
        "run_id": run_id, "snapshot_id": snapshot_id, "report_date": run.run_date, "generation_mode": mode,
        "window_start": collect.window_start, "window_end": collect.window_end,
        "news": news, "clues": clues, "ai_daily": ai_daily,
        "coverage_notes": coverage_notes, "news_errors": news_errors,
        "personal": personal_ctx,
    }
    if getattr(deps, "progress", None) is None:
        deps.progress = tracker  # 节点级阶段跟踪
    deps.cancel_token = cancel_token
    check_cancel(cancel_token)
    try:
        final = asyncio.run(_execute(deps, initial, run_id))
    except ModelNotAllowedError as exc:
        run.status = "failed"
        run.error = f"模型路由阻塞: {exc}"
        run.finished_at = _now()
        mr.commit()
        log_run(mr, run_id, "generate", run.error, level="error")
        raise

    tracker.stage_progress("collect", data={"selected_by_category": {
        category: len(final.get("news_selection", {}).get(category, []))
        for category in ("domestic", "international", "ai")}})
    # 5) 结果落库状态
    degraded = [bool(coverage_notes) or personal_ctx.get("source_meta", {}).get("status") in ("failed", "empty"),
                final["goal_result"].get("status") == "failed" and "目标分析缺失",
                final["advice_result"].get("status") == "failed" and "建议分析失败"]
    run.status = "degraded" if any(degraded) else "success"
    run.snapshot_id = snapshot_id
    run.finished_at = _now()
    mr.commit()
    log_run(mr, run_id, "publish", "晨报已发布", detail=final.get("publish"))

    tracker.stage_completed("publish",
                            summary=f"版本 v{(final.get('publish') or {}).get('version_no')} 已发布",
                            data=final.get("publish"))
    return {"status": run.status, "publish": final.get("publish")}


def _load_personal(hub_session_factory, window_start: str, window_end: str) -> dict:
    """从 hub 只读加载个人上下文；无 factory（纯单测）时返回空上下文。"""

    from ..services import hub_readonly

    if hub_session_factory is None:
        return {"daily_done": [], "daily_pending": [], "longterm_highlight": [],
                "longterm_active": [], "important_infos": []}
    with hub_session_factory() as hub:
        ctx = hub_readonly.load_personal_context(hub, window_start, window_end)
    return ctx.__dict__


async def _execute(deps: WorkflowDeps, initial: dict, run_id: int) -> dict:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ..db import make_engine
    from ..config import get_mr_settings

    db_path = deps.mr_session_factory.kw["bind"].url.database  # type: ignore[attr-defined]
    g = build_workflow(deps).compile()
    # Checkpoint：独立 sqlite 文件（避免与 SQLAlchemy 连接争用）
    async with AsyncSqliteSaver.from_conn_string(f"{db_path}.checkpoint") as saver:
        g = build_workflow(deps).compile(checkpointer=saver)
        final = await g.ainvoke(initial, config={"configurable": {"thread_id": f"mr-run-{run_id}"},
            "metadata": {"mr_run_id": run_id}})
    return final


class _ClientShim:
    """record_usage 需要 client 形态，此处仅携带 model/base_url。"""

    def __init__(self, model: str, base_url: str):
        self.model = model
        self.base_url = base_url


def _trim_for_llm(news: list[dict]) -> list[dict]:
    """LLM 输入截断：每类按时间倒序保留上限（国内120/国际80），防上下文溢出。

    截断只影响分析输入，DB 与索引保留全量；AI 日报条目不经此截断（确定性组装，见 ai_daily）。
    """

    caps = {"domestic": 120, "international": 80, "ai": 60}
    by_cat: dict[str, list[dict]] = {}
    for n in news:
        by_cat.setdefault(n["category"], []).append(n)
    out: list[dict] = []
    for cat, items in by_cat.items():
        items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
        out.extend(items[: caps.get(cat, 80)])
    return out


def _snapshot_personal(mr: Session, run_id: int, snapshot_id: str, ctx: dict) -> None:
    """个人事件证据快照（只读 hub 的当期副本；不倒推历史）。"""

    from ..models import PersonalEventSnapshot

    def add(table: str, records: list[dict], time_key: str = "completed_at"):
        for rec in records:
            mr.add(PersonalEventSnapshot(
                run_id=run_id, snapshot_id=snapshot_id, source_table=table,
                record_id=rec.get("id", 0), event_time=rec.get(time_key),
                summary=rec.get("title", "")[:200], payload=rec,
            ))

    add("daily_tasks", ctx.get("daily_done", []))
    add("long_term_plans", ctx.get("longterm_highlight", []), time_key="target_date")
    mr.commit()
