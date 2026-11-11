"""APScheduler 调度：每天北京时间 08:00 一期（采集+生成），错过启动时间则立即补跑一期。

- 仅进程内调度（不引入常驻守护进程，AGENTS §3 铁律 4）；
- 实际执行仍走 MorningRunner（run_records 状态机），调度器只负责触发；
- 测试环境经 schedule_enabled=False 关闭。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def create_scheduler(settings, runner, mr_session_factory, hub_session_factory):
    """返回 (scheduler, job_fn)；job_fn 提交当期日采集+生成。"""

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    from ..services import report_service

    def daily_job() -> None:
        today = datetime.now(CST).date().isoformat()
        with mr_session_factory() as mr:
            from ..models import RunRecord
            from sqlalchemy import select

            exists = mr.execute(
                select(RunRecord.id).where(
                    RunRecord.run_date == today, RunRecord.kind == "generate",
                    RunRecord.status.in_(["success", "degraded", "running", "pending"]))
                .limit(1)).first()
            if exists:
                logger.info("今日 08:00 任务已存在，跳过（防重复触发）")
                return
            run = RunRecord(run_date=today, kind="generate", status="pending")
            mr.add(run)
            mr.commit()
            run_id = run.id
        ok = runner.submit("generate", run_id, _generate_fn(settings, hub_session_factory, mr_session_factory))
        if not ok:
            logger.warning("08:00 生成任务提交冲突（已有运行中）")

    def _generate_fn(settings, hub_sf, mr_sf):
        def fn(mr, run_id):
            token = runner.token_for(run_id)
            report_service.run_generate(
                mr, run_id, settings, mode="auto",
                hub_session_factory=hub_sf, mr_session_factory=mr_sf,
                cancel_token=token)
        return fn

    scheduler = BackgroundScheduler(timezone=CST)
    scheduler.add_job(
        daily_job,
        CronTrigger(hour=settings.schedule_hour, minute=settings.schedule_minute, timezone=CST),
        id="morning_daily_0800",
        max_instances=1,
        coalesce=True,
    )
    return scheduler, daily_job
