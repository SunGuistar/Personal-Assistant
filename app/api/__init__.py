"""首页 API 装配；非首页模块在后台独立加载。"""
from fastapi import APIRouter


def build_home_router():
    from .health import router as health
    from .plans import router as plans
    from .tasks import router as tasks
    from .jobs import router as jobs
    from .infos import infos_router, memos_router
    from .daily_questions import router as questions
    router = APIRouter(prefix="/api")
    for item in (health, plans, tasks, jobs, infos_router, memos_router, questions):
        router.include_router(item)
    return router
