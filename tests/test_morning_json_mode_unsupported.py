"""模型不支持 JSON mode 时必须显式报 JsonModeUnsupportedError，禁止静默降级；零外网。"""
import httpx
import pytest
import respx
from openai import BadRequestError

from app.morning_report.services.llm_router import (
    ChatClient, JsonModeUnsupportedError, json_mode_error_from)

BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
UNSUPPORTED_MSG = "Invalid response format type specified: json_object is not supported for this model"
UNRELATED_MSG = "messages must contain at least one user message"


def _error_payload(message: str) -> dict:
    return {"error": {"code": "invalid_request_error", "type": "invalid_request_error",
                      "param": "thinking", "code_inner": None, "message": message}}


def test_chat_raises_json_mode_unsupported(monkeypatch):
    monkeypatch.setenv("TEST_MR_KEY", "test-key")
    client = ChatClient(BASE, "TEST_MR_KEY", "qwen3.7-plus")
    with respx.mock() as mock:
        route = mock.post(BASE + "/chat/completions").respond(
            400, json=_error_payload(UNSUPPORTED_MSG))
        with pytest.raises(JsonModeUnsupportedError, match="qwen3.7-plus"):
            client.chat([{"role": "user", "content": "output JSON"}])
        assert route.call_count == 1  # 不重试、不去掉 JSON mode 再发


def test_chat_reraises_unrelated_bad_request(monkeypatch):
    monkeypatch.setenv("TEST_MR_KEY", "test-key")
    client = ChatClient(BASE, "TEST_MR_KEY", "qwen3.7-plus")
    with respx.mock() as mock:
        mock.post(BASE + "/chat/completions").respond(400, json=_error_payload(UNRELATED_MSG))
        with pytest.raises(BadRequestError):
            client.chat([{"role": "user", "content": "output JSON"}])


@pytest.mark.parametrize("message", [UNSUPPORTED_MSG, UNRELATED_MSG, "plain error without hints"])
def test_json_mode_error_from_markers(message):
    request = httpx.Request("POST", BASE + "/chat/completions")
    response = httpx.Response(400, json=_error_payload(message), request=request)
    exc = BadRequestError(message, response=response, body=_error_payload(message))
    converted = json_mode_error_from(exc, "m1")
    if message == UNSUPPORTED_MSG:
        assert converted is not None and "m1" in str(converted)
    else:
        assert converted is None


def test_subagent_raises_json_mode_unsupported(monkeypatch):
    """LangChain Subagent 路径同样显式失败，工作流节点降级后记录明确错误名。"""
    from app.morning_report.graph.subagents import LangChainSubagentRunner
    from app.morning_report.config import MRSettings
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    runner = LangChainSubagentRunner(MRSettings())
    runner.configure_context({"daily_pending": [{"source_id": "daily_tasks:1", "title": "项目", "done": False}]}, None)
    with respx.mock() as mock:
        route = mock.post(BASE + "/chat/completions").respond(
            400, json=_error_payload(UNSUPPORTED_MSG))
        with pytest.raises(JsonModeUnsupportedError, match=runner._settings.dashscope_model):
            runner.run("goal_analysis", "请输出 JSON", runner.tools_for("goal_analysis"))
        assert route.call_count == 1


def test_subagent_unrelated_bad_request_passthrough(monkeypatch):
    from app.morning_report.graph.subagents import LangChainSubagentRunner
    from app.morning_report.config import MRSettings
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    runner = LangChainSubagentRunner(MRSettings())
    runner.configure_context({"daily_pending": [{"source_id": "daily_tasks:1", "title": "项目", "done": False}]}, None)
    with respx.mock() as mock:
        mock.post(BASE + "/chat/completions").respond(400, json=_error_payload(UNRELATED_MSG))
        with pytest.raises(BadRequestError):
            runner.run("advice", "请输出 JSON", runner.tools_for("advice"))
