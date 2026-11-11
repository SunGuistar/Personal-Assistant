"""阶段进度跟踪：驱动晨报生成进度面板的数据层。

- 阶段状态落库 `run_stages`（追加迁移 v2，历史数据兼容）；技术日志仍在 `run_logs`。
- 每阶段一行，原地更新（重入 attempts+1）；任何更新刷新 last_event_at 作为活跃心跳。
- 快照接口向前端提供完整阶段列表 + 运行状态 + 服务器时间 + 卡住阈值；SSE 以 seq 增量推送。
- structured_data 经脱敏（掩 API Key 形态、剔除 prompt 字段）后才落库。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta

from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models import RunRecord, RunStage, RunLog

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# 完整阶段定义（顺序即展示顺序；映射真实 LangGraph 工作流与采集管线，不得虚构）
STAGE_DEFS: list[dict] = [
    {"stage": "collect", "title": "资讯采集", "group": None},
    {"stage": "index", "title": "索引同步与检查", "group": None},
    {"stage": "snapshot", "title": "数据快照", "group": None},
    {"stage": "info_analysis", "title": "资讯分析", "group": None},
    {"stage": "personal_analysis", "title": "个人分析", "group": None},
    {"stage": "tech_research", "title": "技术研究 Subagent", "group": "parallel_analysis"},
    {"stage": "goal_analysis", "title": "目标分析 Subagent", "group": "parallel_analysis"},
    {"stage": "advice", "title": "建议 Subagent", "group": None},
    {"stage": "editor", "title": "主编整合", "group": None},
    {"stage": "quality_eval", "title": "质量评价", "group": None},
    {"stage": "publish", "title": "发布归档", "group": None},
]
STAGE_ORDER = {d["stage"]: i for i, d in enumerate(STAGE_DEFS)}
TERMINAL_RUN_STATUS = ("success", "failed", "degraded", "cancelled")
ACTIVE_RUN_STATUS = ("pending", "running", "stopping")

_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")
_SENSITIVE_KEYS = {"prompt", "prompts", "api_key", "apikey", "authorization", "messages", "system"}


def _now() -> str:
    return datetime.now(CST).isoformat()


def sanitize(data):
    """递归脱敏：掩 API Key 形态；剔除 prompt/messages 等敏感字段。"""

    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                continue
            out[k] = sanitize(v)
        return out
    if isinstance(data, list):
        return [sanitize(v) for v in data]
    if isinstance(data, str):
        return _KEY_RE.sub("sk-***", data)
    return data


def _elapsed_ms(started: str | None, finished: str | None = None) -> int | None:
    if not started:
        return None
    try:
        s = datetime.fromisoformat(started)
        e = datetime.fromisoformat(finished) if finished else datetime.now(CST)
        return max(0, int((e - s).total_seconds() * 1000))
    except ValueError:
        return None


class _SessionShim:
    """把单个 Session 伪装成 sessionmaker（仅用于明确单线程的调用方）。"""

    def __init__(self, session: Session):
        self._s = session

    def __call__(self):
        return _ShimCtx(self._s)


class _ShimCtx:
    def __init__(self, s):
        self._s = s

    def __enter__(self):
        return self._s

    def __exit__(self, *exc):
        return False


class ProgressTracker:
    """单 run 的阶段跟踪器。线程安全：每次操作经会话工厂开短会话。

    传 sessionmaker 为生产路径；传单个 Session 时仅允许单线程调用方（测试/管线内）。
    """

    def __init__(self, session_or_factory, run_id: int):
        self._sf = (session_or_factory if isinstance(session_or_factory, sessionmaker)
                    else _SessionShim(session_or_factory))
        self.run_id = run_id

    @contextmanager
    def _s(self):
        with self._sf() as mr:
            yield mr

    def _row(self, mr: Session, stage: str) -> RunStage | None:
        return mr.execute(
            select(RunStage).where(RunStage.run_id == self.run_id, RunStage.stage == stage)
        ).scalars().first()

    # ---------- 阶段事件 ----------

    def stage_started(self, stage: str, summary: str = "") -> None:
        if stage not in STAGE_ORDER:
            logger.warning("未知阶段: %s", stage)
        with self._s() as mr:
            row = self._row(mr, stage)
            now = _now()
            if row is None:
                d = STAGE_DEFS[STAGE_ORDER.get(stage, 0)]
                row = RunStage(run_id=self.run_id, stage=stage,
                               sort_order=STAGE_ORDER.get(stage, 99),
                               parent_stage=d.get("group"), title=d["title"], attempts=1)
                mr.add(row)
            else:
                # 每次进入记一次尝试，开始时间保留首次
                row.attempts = (row.attempts or 0) + 1
            row.status = "running"
            row.started_at = row.started_at or now
            row.finished_at = None
            row.last_event_at = now
            if summary:
                row.summary = summary
            mr.commit()

    def stage_progress(self, stage: str, summary: str | None = None, data: dict | None = None) -> None:
        with self._s() as mr:
            row = self._row(mr, stage)
            if row is None:
                mr.commit()
                self.stage_started(stage)
                return self.stage_progress(stage, summary, data)
            if summary:
                row.summary = summary
            if data:
                merged = dict(row.data or {})
                merged.update(sanitize(data))
                row.data = merged
            row.last_event_at = _now()
            mr.commit()

    def stage_completed(self, stage: str, summary: str = "", data: dict | None = None,
                        status: str = "success", reason: str = "") -> None:
        with self._s() as mr:
            row = self._row(mr, stage)
            if row is None:
                mr.commit()
                self.stage_started(stage)
                return self.stage_completed(stage, summary, data, status, reason)
            now = _now()
            row.status = status  # success/warning/skipped
            if summary:
                row.summary = summary
            if data:
                merged = dict(row.data or {})
                merged.update(sanitize(data))
                row.data = merged
            row.reason = reason or row.reason
            row.finished_at = now
            row.last_event_at = now
            row.elapsed_ms = _elapsed_ms(row.started_at, now)
            mr.commit()

    def stage_failed(self, stage: str, reason: str, data: dict | None = None) -> None:
        with self._s() as mr:
            row = self._row(mr, stage)
            if row is None:
                mr.commit()
                self.stage_started(stage)
                return self.stage_failed(stage, reason, data)
            now = _now()
            row.status = "failed"
            row.reason = reason[:500]
            if data:
                merged = dict(row.data or {})
                merged.update(sanitize(data))
                row.data = merged
            row.finished_at = now
            row.last_event_at = now
            row.elapsed_ms = _elapsed_ms(row.started_at, now)
            mr.commit()


# ---------- 快照 / 恢复 ----------

def snapshot(mr: Session, run_id: int, stall_seconds: int = 150) -> dict:
    """完整进度快照：运行状态 + 阶段列表（含未开始）+ 最近动态 + 服务器时间与阈值。"""

    run = mr.get(RunRecord, run_id)
    if run is None:
        return {"run": None, "stages": [], "recent": []}
    stage_rows = mr.execute(
        select(RunStage).where(RunStage.run_id == run_id).order_by(RunStage.sort_order)
    ).scalars().all()
    by_stage = {r.stage: r for r in stage_rows}
    stages = []
    for d in STAGE_DEFS:
        row = by_stage.get(d["stage"])
        stages.append({
            "stage": d["stage"],
            "title": d["title"],
            "group": d["group"],
            "status": row.status if row else "pending",
            "summary": row.summary if row else "",
            "reason": row.reason if row else "",
            "started_at": row.started_at if row else None,
            "finished_at": row.finished_at if row else None,
            "elapsed_ms": row.elapsed_ms if row else None,
            "attempts": row.attempts if row else 0,
            "last_event_at": row.last_event_at if row else None,
            "data": row.data if row else None,
        })
    recent = [
        {"id": l.id, "at": l.at, "stage": l.stage, "level": l.level, "message": l.message}
        for l in mr.execute(
            select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.id.desc()).limit(5)
        ).scalars().all()
    ][::-1]
    done = sum(1 for s in stages if s["status"] in ("success", "skipped"))
    return {
        "run": {
            "id": run.id, "run_date": run.run_date, "kind": run.kind, "status": run.status,
            "error": run.error, "started_at": run.started_at, "finished_at": run.finished_at,
        },
        "active": run.status in ACTIVE_RUN_STATUS,
        "stages": stages,
        "recent": recent,
        "done_count": done,
        "total_count": len(stages),
        "server_now": _now(),
        "stall_seconds": stall_seconds,
    }


def active_run(mr: Session, report_date: str) -> RunRecord | None:
    """当日活动任务（pending/running 优先），否则当日最近一个任务（用于展示终态）。"""

    active = mr.execute(
        select(RunRecord).where(
            RunRecord.run_date == report_date, RunRecord.kind == "generate",
            RunRecord.status.in_(ACTIVE_RUN_STATUS),
        ).order_by(RunRecord.id.desc()).limit(1)
    ).scalars().first()
    if active is not None:
        return active
    return mr.execute(
        select(RunRecord).where(
            RunRecord.run_date == report_date, RunRecord.kind == "generate",
        ).order_by(RunRecord.id.desc()).limit(1)
    ).scalars().first()


def interrupt_stale_stages(mr: Session) -> int:
    """进程重启后，遗留 running 阶段标记 interrupted（与 run_records 启动清理配套）。"""

    from sqlalchemy import update

    rows = mr.execute(
        update(RunStage).where(RunStage.status == "running")
        .values(status="interrupted", reason="进程重启，阶段状态待确认",
                finished_at=_now())
    ).rowcount
    mr.commit()
    return rows or 0
