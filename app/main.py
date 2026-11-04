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

    app = FastAPI(title="Personal Hub", version="0.1.0")
    register_exception_handlers(app)

    engine = make_engine(settings.db_url)
    session_factory = make_session_factory(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.task_runner = TaskRunner(session_factory)

    from .services import wechat_jobs

    wechat_jobs.configure(app.state.task_runner)  # summarize_chat 工具经此提交后台总结任务

    app.include_router(api_router)

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
