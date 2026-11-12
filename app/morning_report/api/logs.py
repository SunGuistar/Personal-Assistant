"""实时运行日志 SSE（V0.6 §4.7）：按 run_id 推送增量日志，支持断开重连（after_id 续传）。"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import RunLog, RunRecord
from .deps import get_mr_session

router = APIRouter()


@router.get("/logs/stream")
def logs_stream(run_id: int, after_id: int = 0, mr: Session = Depends(get_mr_session)):
    """EventSource：先发 after_id 之后的存量日志，之后每 1s 轮询增量；客户端断线重连传 after_id。"""

    def gen():
        last = after_id
        idle_rounds = 0
        while True:
            rows = mr.execute(
                select(RunLog).where(RunLog.run_id == run_id, RunLog.id > last)
                .order_by(RunLog.id).limit(200)
            ).scalars().all()
            if rows:
                idle_rounds = 0
                for r in rows:
                    last = r.id
                    yield {"data": json.dumps({
                        "id": r.id, "at": r.at, "stage": r.stage,
                        "level": r.level, "message": r.message, "detail": r.detail,
                    }, ensure_ascii=False)}
            else:
                idle_rounds += 1
                run = mr.execute(select(RunRecord).where(RunRecord.id == run_id)).scalars().first()
                done = run is not None and run.status in ("success", "failed", "degraded")
                if done and idle_rounds >= 2:
                    yield {"data": json.dumps({"done": True, "status": run.status}, ensure_ascii=False)}
                    break
                time.sleep(1)
            mr.commit()  # 刷新会话可见性

    return EventSourceResponse(gen())
