"""主编 LangChain 接入与父子追踪；假 HTTP、回调，不上传 LangSmith。"""
import asyncio
import json
import pytest
import respx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from app.morning_report.services.llm_router import ChatClient
from app.morning_report.graph.workflow import build_workflow
from tests.test_morning_stage4_graph import _deps, _initial, REPORT_MD


@pytest.fixture(autouse=True)
def no_live_tracing(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("TEST_EDITOR_KEY", "test-key")


def completion():
    return {"id": "mock-editor", "object": "chat.completion", "created": 0, "model": "qwen3.7-plus",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content":
            json.dumps({"content_md": REPORT_MD}, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 7, "total_tokens": 37,
                  "prompt_tokens_details": {"cached_tokens": 10}}}


@pytest.mark.parametrize("base,model,thinking_key", [
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.7-plus", "enable_thinking"),
    ("https://api.deepseek.com", "deepseek-flash", "chat_template_kwargs")])
def test_editor_langchain_preserves_http_contract_and_usage(base, model, thinking_key):
    client = ChatClient(base, "TEST_EDITOR_KEY", model, thinking=False)
    assert isinstance(client._client, ChatOpenAI)
    with respx.mock() as mock:
        route = mock.post(base + "/chat/completions").respond(200, json=completion())
        result = client.chat([{"role": "system", "content": "Return JSON"}, {"role": "user", "content": "test"}])
    body = json.loads(route.calls[0].request.content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == model
    assert body[thinking_key] == (False if thinking_key == "enable_thinking" else {"thinking": False})
    assert (result.input_tokens, result.output_tokens) == (30, 7)
    assert result.cache_hit_tokens == 10 and result.cache_miss_tokens == 20
    assert json.loads(result.content)["content_md"] == REPORT_MD
    assert client._client.max_retries == 2


def test_editor_node_publishes_without_llm_run_or_token_usage(fclient):
    chains, llms, ends, recorded = [], [], [], []
    class Capture(BaseCallbackHandler):
        def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
            chains.append((kwargs.get("name"), run_id, parent_run_id))
        def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
            llms.append((run_id, parent_run_id, kwargs.get("metadata", {}), kwargs.get("name")))
        def on_llm_end(self, response, **kwargs):
            ends.append(response)
    client = ChatClient("https://dashscope.aliyuncs.com/compatible-mode/v1", "TEST_EDITOR_KEY", "qwen3.7-plus")
    deps = _deps(fclient, llm=client)
    deps.recorder = lambda node, result, *a: recorded.append((node, result))
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(client.base_url + "/chat/completions").respond(200, json=completion())
        final = asyncio.run(build_workflow(deps).compile().ainvoke(_initial(),
            config={"callbacks": [Capture()], "metadata": {"mr_run_id": 123}}))
        assert route.call_count == 0
    assert final["publish"]["version_id"]
    assert llms == ends == recorded == []
    assert any(name == "editor" for name, _, _ in chains)
