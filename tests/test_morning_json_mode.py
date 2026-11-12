"""晨报所有 LLM 调用必须携带 JSON mode，工具调用和 Markdown 正文解包均需兼容。"""
import json
import httpx
from types import SimpleNamespace
import pytest
import respx
from app.morning_report.services.llm_router import ChatClient, ChatResult
from app.morning_report.graph.workflow import node_editor, _json_of
from tests.test_morning_stage4_graph import _initial, REPORT_MD


def completion(content, tools=None):
    message = {"role": "assistant", "content": content}
    if tools: message["tool_calls"] = tools
    return {"id": "mock", "object": "chat.completion", "created": 0, "model": "qwen3.7-plus",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if tools else "stop", "message": message}]}


@pytest.mark.parametrize("base,model", [("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.7-plus"),
                                        ("https://api.deepseek.com", "deepseek-flash")])
def test_default_chat_requests_json_and_cannot_disable(monkeypatch, base, model):
    monkeypatch.setenv("TEST_MR_KEY", "test-key")
    client = ChatClient(base, "TEST_MR_KEY", model)
    with respx.mock() as mock:
        route = mock.post(base + "/chat/completions").respond(200, json=completion("{}"))
        client.chat([{"role": "user", "content": "output JSON"}])
        assert json.loads(route.calls[0].request.content)["response_format"] == {"type": "json_object"}
        with pytest.raises(ValueError, match="JSON"):
            client.chat([{"role": "user", "content": "output JSON"}], json_mode=False)
        assert route.call_count == 1


@pytest.mark.parametrize("value", ["plain text", '```json\n{}\n```', 'prefix {}', '[]', 'null', '{"a": NaN}', '{"a": 1, "a": 2}'])
def test_json_contract_rejects_non_objects_and_non_json(value):
    with pytest.raises(ValueError):
        _json_of(value)


@pytest.mark.parametrize("payload", [{}, {"content_md": None}, {"content_md": []}, {"content_md": "  "}])
def test_editor_rejects_missing_or_invalid_markdown(payload):
    state = _initial()
    state.update(goal_result={}, advice_result={}, news_selection={})
    def chat(messages, *, json_mode):
        assert json_mode is True
        assert "JSON" in messages[0]["content"]
        return ChatResult(content=json.dumps(payload))
    deps = SimpleNamespace(cancel_token=None, progress=None, llm=SimpleNamespace(chat=chat), record=lambda *a: None)
    with pytest.raises(ValueError, match="content_md"):
        node_editor(state, deps)


@pytest.mark.parametrize("stage", ["goal_analysis", "advice"])
def test_json_mode_survives_real_agent_tool_loop(monkeypatch, stage):
    from app.morning_report.graph.subagents import LangChainSubagentRunner
    from app.morning_report.config import MRSettings
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    runner = LangChainSubagentRunner(MRSettings())
    runner.configure_context({"daily_pending": [{"source_id": "daily_tasks:1", "title": "项目", "done": False}]}, None)
    response = {"status": "finished"}
    with respx.mock() as mock:
        route = mock.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").mock(side_effect=[
            httpx.Response(200, json=completion(None, [{"id": "call1", "type": "function", "function": {
                "name": "search_personal_records", "arguments": json.dumps({"query": "项目"})}}])),
            httpx.Response(200, json=completion(json.dumps(response))),
        ])
        assert json.loads(runner.run(stage, "请输出 JSON", runner.tools_for(stage))) == response
        assert route.call_count == 2
        for call in route.calls:
            body = json.loads(call.request.content)
            assert body["response_format"] == {"type": "json_object"}
            assert body["enable_thinking"] is False
        assert runner.last_tool_calls[stage] == 1
        assert runner.evidence[stage][0]["source_id"] == "daily_tasks:1"


def test_editor_decodes_json_and_keeps_markdown_output():
    state = _initial()
    state.update(goal_result={}, advice_result={}, news_selection={"domestic": [{"id": 1}], "international": [{"id": 2}]})
    def chat(messages, *, json_mode):
        assert json_mode is True
        return ChatResult(content=json.dumps({"content_md": REPORT_MD}, ensure_ascii=False))
    deps = SimpleNamespace(cancel_token=None, progress=None, llm=SimpleNamespace(chat=chat), record=lambda *a: None)
    draft = node_editor(state, deps)["draft"]
    assert draft.startswith("# 今日晨报")
    assert "## 一、开篇速览" in draft and "## 五、信息说明" in draft
    assert "https://example.com/d1" in draft and "{{AI_NEWS_LIST}}" not in draft
    assert '"content_md"' not in draft
