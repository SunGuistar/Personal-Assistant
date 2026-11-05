"""每周回顾 API 集成测试（fclient 隔离客户端 + Fake Agent/LLM，零付费零外网）。

覆盖：草稿幂等、对话 SSE 与 token 记录、正式周报只读 409、建议生成 SSE、
处置与确认门禁、同周唯一、业务数据零改动。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import DailyTask, TokenUsage

WEEK = "2026-06-01"


class _Chunk:
    def __init__(self, content: str) -> None:
        self.content = content


class _Output:
    usage_metadata = {"input_tokens": 10, "output_tokens": 5}


class FakeAgent:
    """模拟回顾 Agent 流：token × 2 + 模型用量。"""

    async def astream_events(self, state, version):
        assert version == "v2"
        yield {"event": "on_chat_model_stream", "data": {"chunk": _Chunk("本周完成")}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": _Chunk(" 1 项任务")}}
        yield {"event": "on_chat_model_end", "data": {"output": _Output()}}


class FakeSuggestLLM:
    model_name = "fake-suggest"

    def invoke(self, prompt: str):
        class _Resp:
            content = json.dumps(
                {
                    "analysis": "API 层分析",
                    "suggestions": [
                        {
                            "content": "建议一",
                            "basis": [{"source_type": "daily_task", "source_id": 1, "reason": "本周任务"}],
                        }
                    ],
                },
                ensure_ascii=False,
            )
            usage_metadata = {"input_tokens": 20, "output_tokens": 8}

        return _Resp()


@pytest.fixture()
def seeded_client(fclient, monkeypatch):
    """seed 业务数据 + Fake Agent/LLM。"""
    factory = fclient.app.state.session_factory
    with factory() as s:
        s.add(DailyTask(task_date=WEEK, title="API 测试任务"))
        s.commit()
    monkeypatch.setattr("app.review_agent.build_agent", lambda *a, **k: FakeAgent())
    monkeypatch.setattr(
        "app.wechat_agent.llm_config.build_llm", lambda *a, **k: FakeSuggestLLM()
    )
    return fclient


def _read_sse(response) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _create_review(client, week=WEEK) -> dict:
    response = client.post("/api/reviews", json={"week_start": week})
    assert response.status_code == 200
    return response.json()


def _business_counts(client):
    with client.app.state.session_factory() as s:
        return len(s.execute(select(DailyTask)).scalars().all())


# ---------- 草稿 ----------


def test_create_review_idempotent(seeded_client):
    first = _create_review(seeded_client, "2026-06-03")  # 周三归一化
    assert first["week_start"] == WEEK and first["status"] == "draft"
    assert first["stats"]["tasks"]["belonging"]["total"] == 1
    second = _create_review(seeded_client, WEEK)
    assert second["id"] == first["id"]

    listing = seeded_client.get("/api/reviews").json()
    assert len(listing) == 1 and listing[0]["pending_suggestions"] == 0


def test_invalid_week_rejected(seeded_client):
    assert seeded_client.post("/api/reviews", json={"week_start": "2026-13-01"}).status_code == 422


# ---------- 对话 SSE ----------


def test_chat_sse_roundtrip_and_usage(seeded_client):
    review = _create_review(seeded_client)
    with seeded_client.stream(
        "POST", f"/api/reviews/{review['id']}/chat", json={"message": "分析本周"}
    ) as response:
        assert response.status_code == 200
        events = _read_sse(response)

    types = [event["type"] for event in events]
    assert types[:2] == ["token", "token"] and types[-1] == "done"
    messages = seeded_client.get(f"/api/reviews/{review['id']}/messages").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "本周完成 1 项任务"

    # 模型用量落 token_usage
    with seeded_client.app.state.session_factory() as s:
        rows = s.execute(select(TokenUsage)).scalars().all()
    assert any(r.ref == f"weekly_review:chat:{review['id']}" for r in rows)


def test_chat_confirmed_review_rejected(seeded_client):
    review = _create_review(seeded_client)
    seeded_client.post(f"/api/reviews/{review['id']}/confirm", json={})
    response = seeded_client.post(
        f"/api/reviews/{review['id']}/chat", json={"message": "继续"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "review_confirmed"


# ---------- 建议生成与处置 ----------


def test_suggest_generate_sse(seeded_client):
    review = _create_review(seeded_client)
    with seeded_client.stream(
        "POST", f"/api/reviews/{review['id']}/suggestions/generate"
    ) as response:
        assert response.status_code == 200
        events = _read_sse(response)
    done = events[-1]
    assert done["type"] == "done" and len(done["suggestions"]) == 1
    assert done["suggestions"][0]["basis"][0]["fact"]

    detail = seeded_client.get(f"/api/reviews/{review['id']}").json()
    assert detail["analysis_md"] == "API 层分析"
    assert detail["suggestions"][0]["status"] == "pending"
    listing = seeded_client.get("/api/reviews").json()
    assert listing[0]["pending_suggestions"] == 1


def test_full_review_flow_business_unchanged(seeded_client):
    review = _create_review(seeded_client)
    before = _business_counts(seeded_client)

    # 对话 + 生成建议 + 处置 + 确认
    with seeded_client.stream(
        "POST", f"/api/reviews/{review['id']}/chat", json={"message": "分析"}
    ) as response:
        _read_sse(response)
    with seeded_client.stream(
        "POST", f"/api/reviews/{review['id']}/suggestions/generate"
    ) as response:
        events = _read_sse(response)
    suggestion = events[-1]["suggestions"][0]

    # 未处置完 → 确认 409
    assert seeded_client.post(f"/api/reviews/{review['id']}/confirm", json={}).status_code == 409
    # 修改建议（modify 需要最终文本）
    bad = seeded_client.put(
        f"/api/reviews/suggestions/{suggestion['id']}",
        json={"action": "modify", "final_content": "  "},
    )
    assert bad.status_code == 422
    ok = seeded_client.put(
        f"/api/reviews/suggestions/{suggestion['id']}",
        json={"action": "modify", "final_content": "调整后的建议"},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "modified"

    # 确认（携带最终正文编辑）
    response = seeded_client.post(
        f"/api/reviews/{review['id']}/confirm",
        json={"analysis_md": "最终分析", "user_notes": "补充说明"},
    )
    assert response.status_code == 200
    confirmed = response.json()
    assert confirmed["status"] == "confirmed" and confirmed["confirmed_at"]

    report = seeded_client.get(f"/api/reviews/{review['id']}/report").json()
    assert "最终分析" in report["report_md"]
    assert "调整后的建议" in report["report_md"]
    assert "补充说明" in report["report_md"]

    # 正式周报只读：再确认 409
    again = seeded_client.post(f"/api/reviews/{review['id']}/confirm", json={})
    assert again.status_code == 409
    # 该周 get_or_create 返回已确认记录
    same = _create_review(seeded_client)
    assert same["id"] == review["id"] and same["status"] == "confirmed"

    # 全流程零业务写
    assert _business_counts(seeded_client) == before
