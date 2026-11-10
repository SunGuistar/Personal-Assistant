# -*- coding: utf-8 -*-
"""阶段 6 验收（后端部分）：SSE 日志增量与断线续传、助手无 Key 降级、chat 提议块解析。"""

from __future__ import annotations

import json
import re

import respx

from app.morning_report.models import RunLog, RunRecord


def _seed_run(fclient, status: str = "success"):
    with fclient.app.state.mr_session_factory() as mr:
        run = RunRecord(run_date="2026-11-10", kind="generate", status=status)
        mr.add(run)
        mr.flush()
        mr.add_all([
            RunLog(run_id=run.id, stage="collect", message="第一条"),
            RunLog(run_id=run.id, stage="index", message="第二条"),
            RunLog(run_id=run.id, stage="publish", message="第三条"),
        ])
        mr.commit()
        return run.id


def _read_stream(fclient, url: str, max_chunks: int = 50) -> list[dict]:
    payloads: list[dict] = []
    with fclient.stream("GET", url) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            for m in re.findall(r"data: (.+)", chunk):
                payloads.append(json.loads(m))
            if any(p.get("done") for p in payloads) or len(payloads) >= max_chunks:
                break
    return payloads


def test_logs_stream_full_then_done(fclient):
    run_id = _seed_run(fclient)
    payloads = _read_stream(fclient, f"/api/morning/logs/stream?run_id={run_id}")
    messages = [p.get("message") for p in payloads if "message" in p]
    assert messages[:3] == ["第一条", "第二条", "第三条"]
    assert any(p.get("done") and p.get("status") == "success" for p in payloads)


def test_logs_stream_resume_after_id(fclient):
    run_id = _seed_run(fclient)
    payloads = _read_stream(fclient, f"/api/morning/logs/stream?run_id={run_id}&after_id=1")
    messages = [p.get("message") for p in payloads if "message" in p]
    assert "第一条" not in messages  # 续传只取增量
    assert "第二条" in messages and "第三条" in messages


def test_assistant_chat_without_key_degrades(fclient, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    resp = fclient.post("/api/morning/assistant/chat", json={"message": "帮我记录偏好"})
    assert resp.status_code == 200
    assert "暂不可用" in resp.text


def test_assistant_proposal_block_parsed(fclient, monkeypatch):
    """有 Key 时走真实 OpenAI 客户端——这里 mock httpx 层流式响应。"""
    import os

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-fake")

    import httpx

    def sse(events: list[dict]) -> bytes:
        out = b""
        for e in events:
            payload = json.dumps(e, ensure_ascii=False)
            out += f"data: {payload}\n\n".encode()
        out += b"data: [DONE]\n\n"
        return out

    text = "好的，我建议记录这条偏好。[MEMORY_PROPOSAL]{\"kind\": \"interest\", \"content\": \"关注数据库技术\"}[/MEMORY_PROPOSAL]"
    chunks = [{"choices": [{"delta": {"content": text[i:i + 4]}}]} for i in range(0, len(text), 4)]

    with respx.mock(assert_all_called=False) as rspx:
        rspx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").respond(
            200, content=sse(chunks),
            headers={"Content-Type": "text/event-stream"})
        resp = fclient.post("/api/morning/assistant/chat", json={"message": "我想关注数据库"})
    assert resp.status_code == 200
    finals = [json.loads(m) for m in re.findall(r"data: (.+)", resp.text) if "proposals" in m]
    assert finals, "应输出 proposals 字段"
    assert finals[-1]["proposals"] == [{"kind": "interest", "content": "关注数据库技术"}]
    assert "MEMORY_PROPOSAL" not in finals[-1]["content"]
