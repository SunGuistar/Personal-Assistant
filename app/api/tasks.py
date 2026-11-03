"""任务状态查询（长任务进度轮询入口，ARCH §4）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from ..schemas import TaskOut
from ..tasks import TaskRunner
from .deps import get_task_runner

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, runner: TaskRunner = Depends(get_task_runner)):
    task = runner.get(task_id)
    result = json.loads(task.result_json) if task.result_json else None
    return TaskOut(
        id=task.id,
        kind=task.kind,
        status=task.status,
        progress=task.progress,
        result=result,
        error=task.error,
    )
