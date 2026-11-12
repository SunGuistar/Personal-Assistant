# -*- coding: utf-8 -*-
"""阶段 6 验收（后端部分）：SSE 日志增量与断线续传、已移除助手接口与 API 契约。"""

from __future__ import annotations

import json
import re


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


def test_assistant_chat_removed(fclient):
    response = fclient.post("/api/morning/assistant/chat", json={"message": "记录偏好"})
    assert response.status_code == 405  # 仅命中全站 GET 回退，不存在 POST 助手路由


def test_removed_features_not_exposed_in_openapi(fclient):
    schema = fclient.get("/openapi.json").json()
    paths = schema["paths"]
    assert not any(path.startswith(("/api/morning/memory", "/api/morning/assistant")) for path in paths)
    assert not any(name.startswith("Memory") for name in schema.get("components", {}).get("schemas", {}))
