"""晨报任务执行器：基于 run_records 状态机的线程执行（hub TaskRunner 属于 hub 库，不混用）。

- 同 kind 仅允许一个 running/pending（DB 查询判重 + 线程锁双保险）；
- 执行函数签名为 fn(mr_session, run_id) -> summary dict；
- 异常落 run_records.error 并记 run_logs，不静默吞掉。
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models import RunRecord

logger = logging.getLogger(__name__)

RunFn = Callable[[Session, int], dict]


class MorningRunner:
    def __init__(self, session_factory: sessionmaker, max_workers: int = 2):
        self._sf = session_factory
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._active_kinds: set[str] = set()

    def _has_unfinished(self, kind: str, exclude_run_id: int | None = None) -> bool:
        q = select(RunRecord.id).where(
            RunRecord.kind == kind, RunRecord.status.in_(["pending", "running"])
        )
        if exclude_run_id is not None:
            q = q.where(RunRecord.id != exclude_run_id)
        with self._sf() as s:
            row = s.execute(q.limit(1)).first()
        return row is not None

    def submit(self, kind: str, run_id: int, fn: RunFn) -> bool:
        """提交执行；同 kind 已有其他未完成运行返回 False（调用方转 409）。"""

        with self._lock:
            if kind in self._active_kinds or self._has_unfinished(kind, exclude_run_id=run_id):
                return False
            self._active_kinds.add(kind)
        self._pool.submit(self._wrap, kind, run_id, fn)
        return True

    def _wrap(self, kind: str, run_id: int, fn: RunFn) -> None:
        try:
            with self._sf() as s:
                fn(s, run_id)
        except Exception as exc:  # 阻塞规则：后台异常必须落库
            logger.exception("晨报任务执行失败: kind=%s run_id=%s", kind, run_id)
            try:
                with self._sf() as s:
                    run = s.get(RunRecord, run_id)
                    if run is not None and run.status in ("pending", "running"):
                        run.status = "failed"
                        run.error = f"{type(exc).__name__}: {exc}"[:500]
                        s.commit()
            except Exception:
                logger.exception("失败状态落库也异常: run_id=%s", run_id)
        finally:
            with self._lock:
                self._active_kinds.discard(kind)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
