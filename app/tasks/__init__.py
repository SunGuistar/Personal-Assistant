"""进程内任务执行器（AGENTS §4.4：长任务必须走任务状态机）。

- 提交即落库（pending），线程池中执行，状态机 pending → running → success|failed；
- 重复提交保护：同 kind 仅允许一个未完成（DB 部分唯一索引兜底）；
- 异常落任务表（error 记类型与摘要，不含敏感正文）。
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..exceptions import TaskConflict
from ..models import Task

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int], None]
TaskFn = Callable[[ProgressCb], Any]


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


class TaskRunner:
    """每个 app 实例一个；线程池执行，任务状态持久化到 tasks 表。"""

    def __init__(self, session_factory: sessionmaker[Session], max_workers: int = 4) -> None:
        self._session_factory = session_factory
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="hub-task"
        )

    def _active_task(self, session: Session, kind: str) -> Task | None:
        statement = select(Task).where(Task.kind == kind, Task.status.in_(["pending", "running"]))
        return session.execute(statement).scalars().first()

    def submit(self, kind: str, payload: dict | None, fn: TaskFn) -> Task:
        """提交任务；同 kind 已有未完成 → TaskConflict(409)。"""

        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with self._session_factory() as session:
            active = self._active_task(session, kind)
            if active is not None:
                raise TaskConflict(f"任务 {kind} 正在执行（id={active.id}），请等待完成后再提交")
            task = Task(kind=kind, status="pending", payload_json=payload_json, progress=0)
            session.add(task)
            session.commit()
            session.refresh(task)
            task_id = task.id

        self._executor.submit(self._run, task_id, fn)
        return self.get(task_id)

    def _update(self, task_id: int, **fields) -> None:
        with self._session_factory() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            for key, value in fields.items():
                setattr(task, key, value)
            task.updated_at = _now()
            session.commit()

    def _run(self, task_id: int, fn: TaskFn) -> None:
        self._update(task_id, status="running", progress=0, error=None)
        started = time.monotonic()

        def progress_cb(value: int) -> None:
            self._update(task_id, progress=max(0, min(int(value), 100)))

        try:
            result = fn(progress_cb)
            result_json = json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:  # 落任务表，不静默（AGENTS §6）
            elapsed = time.monotonic() - started
            message = f"{type(exc).__name__}: {exc}"
            self._update(task_id, status="failed", error=message[:500])
            logger.warning("task %s failed after %.1fs: %s", task_id, elapsed, message)
            return
        elapsed = time.monotonic() - started
        self._update(task_id, status="success", progress=100, result_json=result_json)
        logger.info("task %s success in %.1fs", task_id, elapsed)

    def get(self, task_id: int) -> Task:
        with self._session_factory() as session:
            task = session.get(Task, task_id)
            if task is None:
                from ..exceptions import NotFoundError

                raise NotFoundError(f"任务不存在: {task_id}")
            session.expunge(task)
            return task
