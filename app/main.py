"""应用装配入口：`uvicorn app.main:app` 或 launcher 启动。

- 每个 app 实例持有独立 engine/session_factory/task_runner（存 app.state，测试可注入临时库）；
- 路由层薄，业务在 services/（后续阶段补充）；
- 静态资源托管 web/dist（不存在时不挂载，服务纯 API）；
- Schema 初始化只认 Alembic（AGENTS §5），本模块不 create_all。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import api_router
from .config import Settings, get_settings
from .db import make_engine, make_session_factory
from .exceptions import register_exception_handlers
from .logging_config import setup_logging
from .tasks import TaskRunner

logger = logging.getLogger(__name__)


def _init_morning_report(app: FastAPI, settings: Settings) -> None:
    """晨报 V2.0 模块装配：独立 SQLite + 独立路由（hub 只读访问经 app.state.session_factory）。"""

    from .morning_report import api as mr_api
    from .morning_report import db as mr_db
    from .morning_report.config import get_mr_settings

    mr_settings = get_mr_settings()
    mr_engine = mr_db.make_engine(settings.data_dir / mr_settings.db_filename)
    mr_db.run_migrations(mr_engine)
    app.state.mr_settings = mr_settings
    app.state.mr_engine = mr_engine
    app.state.mr_session_factory = mr_db.make_session_factory(mr_engine)

    from .morning_report.services.runner import MorningRunner

    app.state.mr_runner = MorningRunner(app.state.mr_session_factory)
    app.include_router(mr_api.morning_router)


class SPAStaticFiles(StaticFiles):
    """单页应用回退：未命中的非 API 路径返回 index.html；/api/* 未命中仍走统一 JSON 404。"""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        from starlette.exceptions import HTTPException as StarletteHTTPException

        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                if str(scope.get("path", "")).startswith("/api/"):
                    raise
                return await super().get_response("index.html", scope)
            raise


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    setup_logging(settings.logs_path)

    app = FastAPI(title="个人助手", version="0.1.0")
    register_exception_handlers(app)

    engine = make_engine(settings.db_url)
    session_factory = make_session_factory(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.task_runner = TaskRunner(session_factory)

    from .services import wechat_jobs

    wechat_jobs.configure(app.state.task_runner)  # summarize_chat 工具经此提交后台总结任务

    _init_morning_report(app, settings)
    app.include_router(api_router)

    @app.on_event("startup")
    def _enqueue_pending_news_translation() -> None:
        """启动时补翻译：TOP 10 中已有缓存但缺少中文翻译的资讯异步翻译一次。

        纯增量（translate_status='' 才入队），同 kind 冲突或 LLM 未配置时静默跳过，
        不影响启动与首页加载。
        """

        from .exceptions import TaskConflict
        from .services import news_translation

        try:
            with session_factory() as session:
                if not news_translation.pending_top_items(session):
                    return
            runner = app.state.task_runner

            def job(_progress_cb):
                with session_factory() as job_session:
                    return news_translation.translate_pending(job_session)

            runner.submit(news_translation.TRANSLATE_KIND, {}, job)
        except TaskConflict:
            logger.info("news.translate 任务已在执行，启动补翻译跳过")
        except Exception as exc:  # 翻译补发失败不阻塞启动
            logger.warning("启动补翻译任务提交失败: %s", f"{type(exc).__name__}: {exc}"[:200])

    @app.on_event("startup")
    def _reconcile_stale_tasks() -> None:
        """进程重启后，上次遗留的 pending/running 任务实际已不在执行。

        一律标记 failed（可重新提交），避免同 kind 被僵尸任务永久 409——
        不依赖进程内锁保证安全（阶段 5 互斥要求）。
        """

        from sqlalchemy import select as _select

        from .models import Task as _Task

        with session_factory() as session:
            stale = session.execute(
                _select(_Task).where(_Task.status.in_(["pending", "running"]))
            ).scalars().all()
            for task in stale:
                task.status = "failed"
                task.error = "进程重启，任务中断（可重新提交）"
            if stale:
                session.commit()
                logger.info("陈旧任务清理: %d 个标记为 failed", len(stale))

    @app.on_event("startup")
    def _ensure_weekly_cleanup_review() -> None:
        """周日生成（错过周日则下次启动补发）本周清理审核记录（幂等）。"""

        from datetime import date as _date

        from .cleanup import service as _cleanup_service

        try:
            with session_factory() as session:
                _cleanup_service.ensure_review(
                    session,
                    today=_date.today(),
                    protected=settings.protected_date_list,
                )
        except Exception as exc:  # 提醒失败不阻塞启动
            logger.warning("清理审核周期初始化失败: %s", f"{type(exc).__name__}: {exc}"[:200])

    @app.on_event("startup")
    def _migrate_legacy_memo() -> None:
        """旧版 memo.md → SQLite 随手备忘的一次性迁移（幂等；不删除原文件）。"""

        from .services import memo_service

        try:
            with session_factory() as session:
                memo_service.migrate_legacy_memo(session)
        except Exception as exc:  # 迁移失败不阻塞启动；旧文件保留可重试
            logger.warning("旧备忘迁移失败（保留原文件）: %s", f"{type(exc).__name__}: {exc}"[:200])

    dist: Path = settings.static_dir
    if (dist / "index.html").exists():
        app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="static")
        logger.info("静态资源托管: %s", dist)
    else:
        logger.warning("未找到前端构建产物 %s，仅提供 API（先执行 npm run build）", dist)

    @app.on_event("shutdown")
    def _dispose_engine() -> None:
        engine.dispose()

    return app
