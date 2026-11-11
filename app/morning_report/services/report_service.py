"""生成编排（每天 08:00 流程 / 手动重新生成共用）。

步骤（V0.6 §五）：清阶段缓存 → 采集(缺则补) → AI 索引同步+必要索引检查(阻塞)
→ 冻结快照 → LangGraph 工作流 → 结果落库。
正式自动用 DeepSeek（时段外阻塞）；手动重新生成可用 DashScope（mode 决定）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters.embedding import DefaultEmbeddingProvider
from ..config import MRSettings
from ..models import Memory, NewsItem, RunRecord
from ..services import index_sync, news_pipeline, progress as progress_mod, stage_cache
from ..services.cancel import check_cancel
from ..services.llm_router import (ModelNotAllowedError, dev_client, formal_client,
                                   record_usage)
from ..services.qdrant_store import QdrantStore
from ..services.rag_tool import RagTool
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

    缓存清理：auto（每天 08:00 新一轮）默认清理；manual 默认复用；clear_cache 显式覆盖
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
    if collect is None or collect.status not in ("success", "degraded"):
        log_run(mr, run_id, "generate", "本期无可用采集，先执行采集", level="warning")
        collect = news_pipeline.create_collect_run(mr, run.run_date)
        news_pipeline.run_collect(mr, collect.id)
        collect = mr.get(RunRecord, collect.id)
        c_rows = mr.execute(select(NewsItem).where(NewsItem.run_id == collect.id)).scalars().all()
        tracker.stage_completed("collect",
                                summary=f"补采完成，{len(c_rows)} 条",
                                data={"saved": len(c_rows)})
    else:
        c_rows_n = mr.execute(select(func.count()).select_from(NewsItem).where(
            NewsItem.run_id == collect.id)).scalar() or 0
        tracker.stage_completed("collect",
                                summary=f"复用本期采集（{c_rows_n} 条）",
                                status="skipped", reason="使用已完成的采集结果")

    check_cancel(cancel_token)
    # 2) AI 索引同步 + 必要索引检查（阻塞规则）
    store = store or QdrantStore(settings.qdrant_url, dense_dims=settings.embedding_dims,
                                 api_key=settings.qdrant_api_key)
    provider = provider or DefaultEmbeddingProvider()
    if deps_override is None:
        # 首日无历史晨报：先确保两个 Collection 存在（空历史不阻塞首期生成）
        store.ensure_collection(settings.collections.tech_news)
        store.ensure_collection(settings.collections.reports)
        tracker.stage_started("index")
        sync = index_sync.sync_tech_news(mr, store, provider, collect.id,
                                         settings.collections.tech_news)
        log_run(mr, run_id, "index", "AI 索引同步完成", detail=sync)
        tracker.stage_completed("index",
                                summary=f"AI 索引 {sync.get('indexed', 0)} 条，一致性 {sync.get('consistency')}",
                                data=sync)
        _recover_dirty_report_index(mr, store, provider, settings)
        problems = index_sync.check_required_indexes(
            mr, store, [settings.collections.tech_news, settings.collections.reports])
        if problems:
            tracker.stage_failed("index", f"必要索引不可用: {problems}")
            run.status = "failed"
            run.error = f"必要索引不可用，按规则阻塞: {problems}"
            run.finished_at = _now()
            mr.commit()
            log_run(mr, run_id, "index", run.error, level="error")
            raise RuntimeError(run.error)

    check_cancel(cancel_token)
    # 3) 冻结快照
    news_rows = mr.execute(select(NewsItem).where(NewsItem.run_id == collect.id)).scalars().all()
    news = [{
        "id": r.id, "category": r.category, "title": r.title, "summary": r.summary or "",
        "source_name": r.source_name, "source_url": r.source_url,
        "published_at": r.published_at, "content_hash": r.content_hash,
        "event_group_id": r.event_group_id,
    } for r in news_rows]
    news = _trim_for_llm(news)
    memory_rows = mr.execute(select(Memory)).scalars().all()
    memory = [{"id": m.id, "kind": m.kind, "content": m.content, "enabled": m.enabled,
               "updated_at": m.updated_at} for m in memory_rows]
    snapshot_id = "snap-" + hashlib.sha1(json.dumps(
        [collect.id, len(news), [m["updated_at"] for m in memory]],
        ensure_ascii=False).encode()).hexdigest()[:16]
    log_run(mr, run_id, "snapshot", f"快照已冻结: {snapshot_id}", detail={"news": len(news)})

    # 4) 工作流
    personal_ctx = personal_ctx_override or _load_personal(hub_session_factory, collect.window_start, collect.window_end)
    _snapshot_personal(mr, run_id, snapshot_id, personal_ctx)
    if deps_override is not None:
        deps = deps_override
    else:
        if mr_session_factory is None:
            raise RuntimeError("生产路径必须注入 mr_session_factory")
        if mode == "auto":
            llm = formal_client(settings)  # 时段外抛 ModelNotAllowedError（不静默切模型）
            client_note = "formal"
        else:
            llm = dev_client(settings)
            client_note = "dev"
        rag = RagTool(store, provider, mr_session_factory)
        def _recorder(node, result, model, base_url):
            from ..services.llm_router import record_usage as _ru
            with mr_session_factory() as s:
                _ru(s, run_id, node, _ClientShim(model, base_url), result,
                    allowed="off_peak" if mode == "auto" else "dev")
        subagents = LangChainSubagentRunner(settings, rag_tool=rag)
        deps = WorkflowDeps(llm=llm, subagents=subagents,
                            mr_session_factory=mr_session_factory, run_id=run_id)
        deps.recorder = _recorder
        log_run(mr, run_id, "generate", f"模型路由: {client_note} ({deps.llm.model})")

    initial = {
        "run_id": run_id, "snapshot_id": snapshot_id, "report_date": run.run_date,
        "window_start": collect.window_start, "window_end": collect.window_end,
        "news": news, "clues": [], "memory": memory,
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

    # 5) 结果落库状态
    if not final.get("fact_check", {}).get("ok"):
        tracker.stage_failed("fact_check", "; ".join(final["fact_check"].get("issues", []))[:300])
        run.status = "failed"
        run.error = "事实校验未通过：" + "; ".join(final["fact_check"].get("issues", []))[:300]
        run.snapshot_id = snapshot_id
        run.finished_at = _now()
        mr.commit()
        log_run(mr, run_id, "publish", run.error, level="error")
        return {"status": "blocked", "fact_check": final["fact_check"]}
    degraded = [final["tech_result"].get("status") == "failed" and "技术研究缺失",
                final["goal_result"].get("status") == "failed" and "目标分析缺失",
                final["advice_result"].get("status") == "failed" and "建议分析失败"]
    fc = final["fact_check"]
    tracker.stage_completed("fact_check",
                            summary="通过" if fc.get("ok") else "未通过",
                            data={"issues_count": len(fc.get("issues", []))})
    ev = final.get("evaluation") or {}
    tracker.stage_completed("quality_eval",
                            status="success" if ev.get("status") == "ok" else "skipped",
                            summary=f"综合分 {ev.get('composite')}" if ev.get("composite") else "评价失败（不阻塞）",
                            reason="" if ev.get("status") == "ok" else "评价模型不可用，按规则标记未评价")
    tracker.stage_started("publish")
    run.status = "degraded" if any(degraded) else "success"
    run.snapshot_id = snapshot_id
    run.finished_at = _now()
    mr.commit()
    log_run(mr, run_id, "publish", "晨报已发布", detail=final.get("publish"))

    # 历史晨报索引更新（V0.6 流程末步）；失败记 dirty 并降级，不阻塞本期已校验内容
    pub = final.get("publish") or {}
    if pub.get("version_id") and store is not None and provider is not None:
        try:
            rs = index_sync.sync_report_version(mr, store, provider, pub["version_id"],
                                                settings.collections.reports)
            log_run(mr, run_id, "index", "历史晨报索引已更新", detail=rs)
        except Exception as exc:
            logger.warning("历史晨报索引更新失败: %s", f"{type(exc).__name__}: {exc}"[:150])
            index_sync._touch_state(mr, settings.collections.reports, "dirty",
                                    f"version {pub['version_id']} sync failed")
            if run.status == "success":
                run.status = "degraded"
                mr.commit()
            log_run(mr, run_id, "index", "历史晨报索引更新失败（已标记 dirty）", level="warning")
    tracker.stage_completed("publish",
                            summary=f"版本 v{(final.get('publish') or {}).get('version_no')} 已发布",
                            data=final.get("publish"))
    return {"status": run.status, "publish": final.get("publish"),
            "fact_check": final["fact_check"], "evaluation": final.get("evaluation")}


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
        final = await g.ainvoke(initial, config={"configurable": {"thread_id": f"mr-run-{run_id}"}})
    return final


class _ClientShim:
    """record_usage 需要 client 形态，此处仅携带 model/base_url。"""

    def __init__(self, model: str, base_url: str):
        self.model = model
        self.base_url = base_url


def _trim_for_llm(news: list[dict]) -> list[dict]:
    """LLM 输入截断：每类按时间倒序保留上限（国内120/国际80/AI60），防上下文溢出。

    截断只影响分析输入，DB 与索引保留全量；信息说明中体现覆盖。
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


def _recover_dirty_report_index(mr: Session, store, provider, settings: MRSettings) -> None:
    """历史晨报索引 dirty 时的恢复检查：重同步最近已发布版本，成功即恢复 ok。"""

    from ..models import IndexState

    row = mr.execute(
        select(IndexState).where(IndexState.collection_name == settings.collections.reports)
    ).scalars().first()
    if row is None or row.status != "dirty":
        return
    from ..models import ReportVersion
    ver = mr.execute(
        select(ReportVersion).where(ReportVersion.status == "published")
        .order_by(ReportVersion.id.desc()).limit(1)
    ).scalars().first()
    if ver is None:
        index_sync._touch_state(mr, settings.collections.reports, "ok", "无已发布版本，恢复为空索引")
        return
    try:
        index_sync.sync_report_version(mr, store, provider, ver.id, settings.collections.reports)
        log_run(mr, 0, "index", f"历史晨报索引已恢复（重同步版本 {ver.id}）")
    except Exception as exc:
        logger.warning("历史晨报索引恢复失败: %s", f"{type(exc).__name__}: {exc}"[:150])
