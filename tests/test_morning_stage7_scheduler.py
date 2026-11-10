# -*- coding: utf-8 -*-
"""阶段 7：调度器防重复触发与任务登记。"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.morning_report.config import MRSettings
from app.morning_report.models import RunRecord
from app.morning_report.services.scheduler import create_scheduler


def test_daily_job_creates_then_skips(fclient):
    settings = MRSettings(schedule_enabled=True)

    class FakeRunner:
        """只记录提交，不真执行（避免调度测试触发真实生成链路）。"""

        def __init__(self):
            self.submitted: list[int] = []

        def submit(self, kind, run_id, fn):
            self.submitted.append(run_id)
            return True

        def shutdown(self):
            pass

    runner = FakeRunner()
    _, daily_job = create_scheduler(
        settings, runner, fclient.app.state.mr_session_factory, None)
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    daily_job()
    with fclient.app.state.mr_session_factory() as mr:
        runs = mr.execute(
            select(RunRecord).where(RunRecord.kind == "generate", RunRecord.run_date == today)
        ).scalars().all()
        assert len(runs) == 1 and runner.submitted == [runs[0].id]
    daily_job()  # 第二次：今日已有记录 → 跳过，不重复建 run、不重复提交
    with fclient.app.state.mr_session_factory() as mr:
        runs = mr.execute(
            select(RunRecord).where(RunRecord.kind == "generate", RunRecord.run_date == today)
        ).scalars().all()
        assert len(runs) == 1 and len(runner.submitted) == 1
