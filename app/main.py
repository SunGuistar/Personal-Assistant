"""应用装配入口：`uvicorn app.main:app` 或 launcher 启动。

- 每个 app 实例持有独立 engine/session_factory/task_runner（存 app.state，测试可注入临时库）；
- 路由层薄，业务在 services/（后续阶段补充）；
- 静态资源托管 web/dist（不存在时不挂载，服务纯 API）；
- Schema 初始化只认 Alembic（AGENTS §5），本模块不 create_all。
"""

from __future__ import annotations

import logging
import asyncio
import time
import traceback
from pathlib import Path

from .startup_timing import stage, timed

with stage("加载 FastAPI"):
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

with stage("加载 API 路由与依赖（含子阶段）"):
    from .api import build_home_router
with stage("加载配置与数据库依赖"):
    from .config import Settings, get_settings
    from .db import make_engine, make_session_factory
    from .exceptions import register_exception_handlers
    from .logging_config import setup_logging
    from .tasks import TaskRunner

logger = logging.getLogger(__name__)


def _build_optional_module(name, app, settings, session_factory):
    """在隔离路由容器装配，完成任务恢复后再一次性发布路由。"""
    staged = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    staged.state = app.state
    if name == "morning":
        _init_morning_report(staged, settings, session_factory)
    elif name == "wechat":
        from .services import wechat_jobs
        from .api.wechat import router as wechat
        from .api.cleanup import router as cleanup
        wechat_jobs.configure(app.state.task_runner)
        staged.include_router(wechat, prefix="/api")
        staged.include_router(cleanup, prefix="/api")
        from datetime import date
        from .cleanup import service
        try:
            with session_factory() as session:
                service.ensure_review(session, today=date.today(), protected=settings.protected_date_list)
        except Exception as exc:
            logger.warning("清理审核提醒初始化失败: %s", type(exc).__name__)
    elif name == "reading":
        from .api.reading import router, notes_router
        staged.include_router(router, prefix="/api")
        staged.include_router(notes_router, prefix="/api")
    elif name == "github":
        from .api.github import router
        staged.include_router(router, prefix="/api")
    return staged


@timed("晨报模块装配（含子阶段）")
def _init_morning_report(app: FastAPI, settings: Settings, hub_session_factory) -> None:
    """晨报 V2.0 模块装配：独立 SQLite + 独立路由（hub 只读访问经 app.state.session_factory）。"""

    with stage("加载晨报路由与依赖"):
        from .morning_report import api as mr_api
        from .morning_report import db as mr_db
        from .morning_report.config import get_mr_settings

    mr_settings = get_mr_settings()
    mr_engine = mr_db.make_engine(settings.data_dir / mr_settings.db_filename)
    with stage("晨报数据库初始化"):
        mr_db.run_migrations(mr_engine)
    app.state.mr_settings = mr_settings
    app.state.mr_engine = mr_engine
    app.state.mr_session_factory = mr_db.make_session_factory(mr_engine)

    with stage("加载晨报任务执行器"):
        from .morning_report.services.runner import MorningRunner

    app.state.mr_runner = MorningRunner(app.state.mr_session_factory)
    app.include_router(mr_api.morning_router)

    # 先恢复任务，再启动调度，避免新任务被误判为旧任务。
    def configure_scheduler():
        if not mr_settings.schedule_enabled:
            return
        from .morning_report.services import scheduler as mr_scheduler

        with stage("装配晨报调度与分析依赖"):
            scheduler, _ = mr_scheduler.create_scheduler(
                mr_settings, app.state.mr_runner,
                app.state.mr_session_factory, hub_session_factory,
            )
        app.state.mr_scheduler = scheduler

        @timed("启动晨报调度器")
        def _start_mr_scheduler() -> None:
            if scheduler.running:
                return
            scheduler.start()
            logger.info("晨报调度已启动：每天 %02d:%02d（Asia/Shanghai）",
                        mr_settings.schedule_hour, mr_settings.schedule_minute)

        _start_mr_scheduler()

    # 进程重启后，遗留的 pending/running 晨报任务实际已不在执行（与 hub 任务同理）
    @app.on_event("startup")
    @timed("恢复晨报中断任务")
    def _reconcile_stale_mr_tasks() -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        from datetime import timedelta as _td

        from sqlalchemy import select as _select

        from .morning_report.models import RunRecord as _MRRun

        def _dt_now() -> str:
            return _dt.now(_tz(_td(hours=8))).isoformat()

        with app.state.mr_session_factory() as s:
            stale = s.execute(
                _select(_MRRun).where(_MRRun.status.in_(["pending", "running"]))
            ).scalars().all()
            for task in stale:
                task.status = "failed"
                task.error = "进程重启，任务中断（可重新提交）"
            if stale:
                s.commit()
                logger.info("晨报陈旧任务清理: %d 个标记为 failed", len(stale))
        from .morning_report.services import progress as _mr_progress
        n = _mr_progress.interrupt_stale_stages(s)
        if n:
            logger.info("晨报中断阶段清理: %d 个标记为 interrupted", n)

    app.router.add_event_handler("startup", configure_scheduler)

    @app.on_event("shutdown")
    def _close_morning_resources():
        scheduler = getattr(app.state, "mr_scheduler", None)
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
        app.state.mr_runner.shutdown()
        mr_engine.dispose()


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


@timed("应用装配（含子阶段）")
def create_app(settings: Settings | None = None, *, defer_modules: bool = True) -> FastAPI:
    with stage("读取配置与初始化日志"):
        settings = settings or get_settings()
        settings.ensure_dirs()
        setup_logging(settings.logs_path)

    app = FastAPI(title="个人助手", version="0.1.0")
    register_exception_handlers(app)
    from .module_startup import ModuleStartup, MODULE_PREFIXES
    from fastapi.responses import JSONResponse
    readiness = ModuleStartup()
    app.state.module_startup = readiness

    @app.middleware("http")
    async def module_gate(request, call_next):
        name = readiness.for_path(request.url.path)
        if name:
            status = readiness.snapshot()["modules"][name]["status"]
            if status != "ready":
                return JSONResponse(status_code=503, headers={"Retry-After": "1"}, content={
                    "detail": {"code": "module_failed" if status == "failed" else "module_loading",
                               "message": "模块初始化失败，请查看启动日志" if status == "failed" else "模块加载中，请稍候"}})
        return await call_next(request)

    with stage("初始化主数据库与任务执行器"):
        engine = make_engine(settings.db_url)
        session_factory = make_session_factory(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.task_runner = TaskRunner(session_factory)

    with stage("加载首页接口"):
        app.include_router(build_home_router())

    @app.on_event("startup")
    @timed("恢复主库中断任务")
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
    @timed("检查旧版备忘迁移")
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

    module_apps = []
    module_tasks = []
    base_routes = list(app.router.routes)
    active_lifespans = 0

    async def load_module(name):
        started = time.perf_counter()
        try:
            with stage(f"后台初始化模块 {name}"):
                staged = await asyncio.to_thread(_build_optional_module, name, app, settings, session_factory)
                lifecycle = staged.router.lifespan_context(staged)
                await lifecycle.__aenter__()
            # 发布在事件循环串行执行；静态兜底路由始终位于最后。
            routes = app.router.routes
            index = next((i for i, route in enumerate(routes) if getattr(route, "name", None) == "static"), len(routes))
            app.router.routes = routes[:index] + staged.router.routes + routes[index:]
            app.openapi_schema = None
            module_apps.append((staged, lifecycle))
            readiness.finish(name, started)
        except Exception as exc:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            logger.error("模块初始化失败: module=%s error_type=%s source=%s:%s",
                         name, type(exc).__name__, Path(frame.filename).name, frame.lineno)
            if name == "morning":
                scheduler = getattr(app.state, "mr_scheduler", None)
                if scheduler and scheduler.running:
                    scheduler.shutdown(wait=False)
                runner = getattr(app.state, "mr_runner", None)
                if runner:
                    runner.shutdown()
                mr_engine = getattr(app.state, "mr_engine", None)
                if mr_engine:
                    mr_engine.dispose()
            readiness.finish(name, started, error=f"初始化失败（{type(exc).__name__}），请查看启动日志")

    @app.on_event("startup")
    async def start_optional_modules():
        nonlocal active_lifespans
        active_lifespans += 1
        if active_lifespans > 1:
            return  # 嵌套客户端复用现有模块，不重复启动调度或跨事件循环等待。
        readiness.home_ready = True
        for name in MODULE_PREFIXES:
            module_tasks.append(asyncio.create_task(load_module(name)))
        if not defer_modules:  # 集成测试可等待所有模块，生产默认首页先行。
            await asyncio.gather(*module_tasks)

    @app.on_event("shutdown")
    async def close_optional_modules():
        nonlocal active_lifespans
        active_lifespans -= 1
        if active_lifespans:
            return
        await asyncio.gather(*module_tasks)
        for staged, lifecycle in reversed(module_apps):
            await lifecycle.__aexit__(None, None, None)
        module_apps.clear()
        module_tasks.clear()
        app.router.routes = list(base_routes)
        app.openapi_schema = None
        readiness.home_ready = False

    @app.on_event("shutdown")
    def _dispose_engine() -> None:
        if active_lifespans == 0:
            engine.dispose()

    return app
