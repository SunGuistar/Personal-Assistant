"""对话 SSE 与总结任务测试（阶段 3.7，Fake Agent/LLM，零付费）。"""

from __future__ import annotations

import json
import threading
import time

import pytest

from app.services import wechat_jobs
from app.wechat_agent.chat_tools import summarizer


class _Chunk:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeAgent:
    """模拟 Agent 流：两个 token + 一个带任务标记的工具返回。"""

    async def astream_events(self, state, version):
        assert version == "v2"
        yield {"event": "on_chat_model_stream", "data": {"chunk": _Chunk("你好")}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": _Chunk("，世界")}}
        yield {
            "event": "on_tool_end",
            "data": {"output": f"{wechat_jobs.JOB_MARKER}99 总结任务已启动（任务 99）"},
        }


@pytest.fixture()
def fake_agent(monkeypatch):
    monkeypatch.setattr("app.wechat_agent.agent.build_agent", lambda: FakeAgent())
    return FakeAgent()


def _read_sse(response) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_chat_sse_roundtrip(fclient, fake_agent):
    with fclient.stream(
        "POST", "/api/wechat/chat", json={"session_id": None, "message": "总结今天的聊天"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _read_sse(response)

    types = [event["type"] for event in events]
    assert types[0] == "token" and events[0]["text"] == "你好"
    assert "summary_job" in types
    assert events[types.index("summary_job")]["task_id"] == 99
    done = events[-1]
    assert done["type"] == "done" and done["session_id"]

    # 历史落库：用户 + 助手各一条
    history = fclient.get(f"/api/wechat/chat/history?session_id={done['session_id']}").json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["messages"][1]["content"] == "你好，世界"


def test_chat_invalid_session(fclient, fake_agent):
    response = fclient.post("/api/wechat/chat", json={"session_id": 999, "message": "hi"})
    assert response.status_code == 404


def test_summary_job_lifecycle_and_duplicate_guard(fclient, monkeypatch):
    wechat_jobs.configure(fclient.app.state.task_runner)
    progress_seen: list[int] = []

    gate = threading.Event()

    def fake_run_summary(date, db_path=None, chat_id=None, progress_cb=None):
        if progress_cb:
            progress_cb(40)
        gate.wait(timeout=5)
        return {"html": "/tmp/fake.html", "png": ""}

    monkeypatch.setattr(wechat_jobs, "run_summary", fake_run_summary)

    job_id = wechat_jobs.submit_summary("2026-11-03", "chat_x")
    time.sleep(0.1)  # 等任务进入 running
    with pytest.raises(Exception) as exc_info:  # TaskConflict(409)
        wechat_jobs.submit_summary("2026-11-03", "chat_x")
    assert "409" in str(exc_info.value.__class__.__mro__[1].__name__) or exc_info.value.__class__.__name__ == "TaskConflict"

    gate.set()
    deadline = time.monotonic() + 5
    task = fclient.app.state.task_runner.get(job_id)
    while task.status != "success" and time.monotonic() < deadline:
        time.sleep(0.05)
        task = fclient.app.state.task_runner.get(job_id)
    assert task.status == "success"
    assert task.result_json and "fake.html" in task.result_json


def test_summarizer_progress_callback_optional(monkeypatch, tmp_path):
    """进度回调为可选增强：传入则按阶段上报，不传行为不变。"""

    monkeypatch.setattr(summarizer, "OUTPUT_ROOT", tmp_path / "Output")
    progress: list[int] = []

    class FakeLLM:
        model_name = "fake-progress-test"

        def invoke(self, messages, **kwargs):
            class R:
                pass

            system = messages[0][1]
            r = R()
            r.content = (
                '{"summary":"总览","highlights":[],"topics":[],"observations":[],"closing":"c"}'
                if "撰写最终日报" in system
                else '{"summary":"s","topics":[{"title":"t","key_points":["k"],"quotes":[]}]}'
            )
            return r

    monkeypatch.setattr(summarizer, "_build_llm", lambda: FakeLLM())
    messages = [
        summarizer.StructuredMessage(
            id=f"m{i}", timestamp=1760000000 + i * 120, time="11-03 10:00",
            sender="甲", text=f"消息{i}", msg_type="文本", render_type="text", chat_id="c",
        )
        for i in range(30)
    ]
    summarizer.run_pipeline("群", messages, progress_cb=progress.append)
    assert progress and progress[0] == 5 and progress[-1] == 95
    assert progress == sorted(progress)  # 单调递增
