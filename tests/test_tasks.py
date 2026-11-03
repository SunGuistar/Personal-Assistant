"""任务状态机：提交 → 执行 → 终态；重复提交保护；API 查询。"""

from __future__ import annotations

import json
import time

import pytest

from app.exceptions import TaskConflict


def _wait_finished(runner, task_id: int, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = runner.get(task_id)
        if task.status in ("success", "failed"):
            return task
        time.sleep(0.02)
    raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内结束")


def test_task_success_lifecycle(task_runner):
    def fn(progress_cb):
        progress_cb(50)
        return {"count": 3}

    task = task_runner.submit("test.success", {"a": 1}, fn)
    finished = _wait_finished(task_runner, task.id)
    assert task_runner.get(task.id).status in ("pending", "running", "success")
    assert finished.status == "success"
    assert finished.progress == 100
    assert json.loads(finished.result_json) == {"count": 3}
    assert finished.error is None


def test_task_failure_recorded(task_runner):
    def fn(progress_cb):
        raise ValueError("boom")

    task = task_runner.submit("test.failure", None, fn)
    finished = _wait_finished(task_runner, task.id)
    assert finished.status == "failed"
    assert "ValueError" in finished.error
    assert finished.result_json is None


def test_duplicate_submit_rejected(task_runner):
    def slow_fn(progress_cb):
        time.sleep(0.6)
        return {"done": True}

    first = task_runner.submit("test.dup", {"x": 1}, slow_fn)
    with pytest.raises(TaskConflict):
        task_runner.submit("test.dup", {"x": 2}, slow_fn)

    finished = _wait_finished(task_runner, first.id)
    assert finished.status == "success"


def test_task_api_roundtrip(client, task_runner):
    task = task_runner.submit("test.api", None, lambda cb: {"ok": True})
    finished = _wait_finished(task_runner, task.id)
    response = client.get(f"/api/tasks/{finished.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["result"] == {"ok": True}
    assert body["kind"] == "test.api"


def test_task_api_not_found(client):
    response = client.get("/api/tasks/999999")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"
