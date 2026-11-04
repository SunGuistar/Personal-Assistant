"""总结任务桥（D2 单通道实现，用户调整三）。

职责边界：`summarize_chat` 工具（Agent 决策调用）经本模块把总结流水线
提交为后台 job；job 内仍是 `run_summary` 原流水线（仅多一个可选进度回调）。
Service/API 层不直接调用 run_summary。

- 防重复：TaskRunner 对同 kind 未完成任务的唯一索引兜底（409）；
  本模块再加进程内锁，避免提交竞态。
- 工具返回值中的 `SUMMARY_JOB_ID:` 标记供 API 层解析，向前端推送
  summary_job 事件。
"""

from __future__ import annotations

import threading
from typing import Any

from ..exceptions import TaskConflict
from app.wechat_agent.chat_tools.summarizer import run_summary

SUMMARY_JOB_KIND = "wechat.summary"
JOB_MARKER = "SUMMARY_JOB_ID:"

_lock = threading.Lock()
_runner: Any = None


def configure(runner: Any) -> None:
    """应用启动时注入 TaskRunner（app/main.py）。"""
    global _runner
    _runner = runner


def is_configured() -> bool:
    return _runner is not None


def submit_summary(date: str, chat_id: str | None) -> int:
    """提交总结任务，返回 job_id；已有同 kind 任务则抛 TaskConflict。"""

    if _runner is None:
        raise RuntimeError("任务执行器未初始化")
    payload = {"date": date, "chat_id": chat_id or ""}

    def job(progress_cb):
        paths = run_summary(date, chat_id=chat_id, progress_cb=progress_cb)
        return {"html": paths["html"], "png": paths["png"]}

    with _lock:
        task = _runner.submit(SUMMARY_JOB_KIND, payload, job)
    return task.id
