"""后台任务状态查询（长任务进度轮询入口，ARCH §4）。

路径为 /api/jobs/*：V1.0 起与每日任务（/api/tasks/*，阶段 2）区分，
避免两类"任务"资源冲突。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from ..schemas import TaskOut
from ..tasks import TaskRunner
from .deps import get_task_runner

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
