"""进度面板 API：完整快照、活动任务、SSE 增量推送（seq 去重）。

- GET /progress?run_id=N        完整进度快照（含未开始阶段、服务器时间、卡住阈值）
- GET /progress/active?report_date=…  当日活动/最近任务（页面加载与多标签页按钮互斥判定）
- GET /progress/stream?run_id=N&after_seq=M  SSE：seq 单调递增，前端按 seq 去重
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...exceptions import NotFoundError
from ..models import RunLog, RunRecord, RunStage
from ..config import get_mr_settings
from ..services import progress as progress_mod
from .deps import get_mr_session

router = APIRouter(prefix="/progress")

CST = timezone(timedelta(hours=8))


def _seq_of(mr: Session, run_id: int) -> int:
    """包含原地阶段更新及任务终态的微秒时间版本，不只依赖插入 ID。"""

    s = mr.execute(select(func.max(RunStage.id)).where(RunStage.run_id == run_id)).scalar() or 0
    l = mr.execute(select(func.max(RunLog.id)).where(RunLog.run_id == run_id)).scalar() or 0
    stamps = list(mr.execute(select(RunStage.last_event_at).where(
        RunStage.run_id == run_id)).scalars())
    stamps.extend(mr.execute(select(RunLog.at).where(RunLog.run_id == run_id)).scalars())
    run = mr.get(RunRecord, run_id)
    if run is not None:
        stamps.extend([run.started_at, run.finished_at])
    return max([s, l] + [int(datetime.fromisoformat(t).timestamp() * 1_000_000)
                             for t in stamps if t])


@router.get("")
def get_progress(run_id: int, mr: Session = Depends(get_mr_session)) -> dict:
    settings = get_mr_settings()
    snap = progress_mod.snapshot(mr, run_id, settings.progress_stall_seconds)
    if snap["run"] is None:
        raise NotFoundError("运行记录不存在")
    snap["seq"] = _seq_of(mr, run_id)
    return snap


@router.get("/active")
def get_active(report_date: str | None = None, mr: Session = Depends(get_mr_session)) -> dict:
    settings = get_mr_settings()
    date = report_date or datetime.now(CST).date().isoformat()
    run = progress_mod.active_run(mr, date)
    if run is None:
        return {"run": None, "stages": [], "active": False, "server_now": datetime.now(CST).isoformat()}
    snap = progress_mod.snapshot(mr, run.id, settings.progress_stall_seconds)
    snap["active"] = run.status in progress_mod.ACTIVE_RUN_STATUS
    snap["seq"] = _seq_of(mr, run.id)
    return snap


@router.get("/stream")
def progress_stream(run_id: int, after_seq: int = 0,
                    mr: Session = Depends(get_mr_session)) -> EventSourceResponse:
    """SSE：快照有变化（seq 增长）即推送完整快照；任务终态后推送 done 并关闭。"""

    settings = get_mr_settings()
    if mr.get(RunRecord, run_id) is None:
        raise NotFoundError("运行记录不存在")
    def gen():
        last_sent = after_seq
        while True:
            # 每轮独立短会话：expire_on_commit=False 的长会话会缓存 running 对象。
            with Session(bind=mr.get_bind()) as fresh:
                snap = progress_mod.snapshot(fresh, run_id, settings.progress_stall_seconds)
                seq = _seq_of(fresh, run_id)
            if snap["run"] is None:
                break
            terminal = snap["run"]["status"] in progress_mod.TERMINAL_RUN_STATUS
            if seq > last_sent or terminal:
                last_sent = seq
                snap["seq"] = seq
                yield {"data": json.dumps(snap, ensure_ascii=False)}
            if terminal:
                yield {"data": json.dumps({"done": True, "status": snap["run"]["status"],
                                           "seq": seq}, ensure_ascii=False)}
                break
            time.sleep(1)

    return EventSourceResponse(gen())
