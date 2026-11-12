"""晨报版本选择与无模型重新组装。"""
from types import SimpleNamespace

from sqlalchemy import func, select

from ...exceptions import DomainError, NotFoundError
from ..models import ReportVersion, RunRecord
from .cancel import check_cancel
from .progress import ProgressTracker, STAGE_DEFS


def latest_per_day(mr):
    latest = select(func.max(ReportVersion.id)).where(
        ReportVersion.status == "published").group_by(ReportVersion.report_date)
    return mr.execute(select(ReportVersion).where(ReportVersion.id.in_(latest)).order_by(
        ReportVersion.report_date.desc())).scalars().all()


def assembly_state(mr, source):
    from .report_news_content import display_sections
    from .report_assembly import display_yesterday
    sections = display_yesterday(mr, source, display_sections(mr, source))
    if not isinstance(sections.get("goal"), dict) or not isinstance(sections.get("advice"), dict):
        raise DomainError("该晨报缺少分析结果，请先重新生成", code="assembly_input_missing", status_code=409)
    saved = sections.get("assembly_input")
    if isinstance(saved, dict):
        inputs = dict(saved)
    else:
        news = sections.get("news_content") or {}
        categories = news.get("categories", {})
        if not isinstance(categories, dict) or not isinstance(sections.get("news_selection"), dict):
            raise DomainError("该晨报缺少资讯组装数据，请先重新生成", code="assembly_input_missing", status_code=409)
        inputs = {"news": [dict(row, source_url=row.get("url") or row.get("source_url", ""))
                             for key in ("domestic", "international") for row in categories.get(key, [])],
                  "ai_daily": categories.get("ai", []), "coverage_notes": [], "news_errors": news.get("errors", {})}
    return {**inputs, "report_date": source.report_date, "snapshot_id": source.snapshot_id,
            "window_start": source.window_start, "window_end": source.window_end,
            "personal": sections.get("assembly_personal") or {},
            "personal_summary": sections.get("personal_summary", ""),
            "news_selection": sections.get("news_selection", {}),
            "goal_result": sections["goal"], "advice_result": sections["advice"],
            "yesterday_content": sections.get("yesterday_content")}


def run_reassemble(mr, run_id, source_id, *, mr_session_factory, cancel_token=None):
    from ..graph.workflow import node_editor, node_publish
    from .progress import _now
    check_cancel(cancel_token)
    source = mr.get(ReportVersion, source_id)
    if source is None or source.status != "published":
        raise NotFoundError("待组装的晨报不存在")
    state = assembly_state(mr, source)
    state.update(run_id=run_id, generation_mode="reassemble")
    run = mr.get(RunRecord, run_id)
    run.status, run.started_at = "running", _now()
    mr.commit()
    tracker = ProgressTracker(mr_session_factory, run_id)
    for stage in STAGE_DEFS:
        if stage["stage"] in ("editor", "publish"):
            break
        tracker.stage_completed(stage["stage"], status="skipped", summary="复用原晨报结果", reason="仅重新组装，不重新采集或分析", data={"source_version_id": source_id})
    deps = SimpleNamespace(cancel_token=cancel_token, progress=tracker, mr_session_factory=mr_session_factory)
    state.update(node_editor(state, deps))
    check_cancel(cancel_token)
    result = node_publish(state, deps)
    run.status, run.finished_at, run.snapshot_id = "success", _now(), source.snapshot_id
    mr.commit()
    tracker.stage_completed("publish", summary="重新组装已发布，不调用模型", data=result["publish"])
    return {"status": "success", **result}
