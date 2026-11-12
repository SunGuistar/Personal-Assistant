"""晨报开发模型路由回归；无真实网络或付费调用。"""
import json
import respx
from app.morning_report.config import MRSettings
from app.morning_report.services.llm_router import ChatClient, dev_client


def test_morning_uses_qwen37_for_manual_and_quality(monkeypatch):
    monkeypatch.delenv("PH_MR_DASHSCOPE_MODEL", raising=False)
    monkeypatch.delenv("PH_MR_QUALITY_EVAL_MODEL", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    settings = MRSettings()
    assert settings.dashscope_model == "qwen3.7-plus"
    assert not hasattr(settings, "quality_eval_model")
    assert dev_client(settings).model == "qwen3.7-plus"


def test_dashscope_explicitly_disables_thinking_for_json(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    client = ChatClient("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY",
                        "qwen3.7-plus", thinking=False)
    with respx.mock() as mock:
        route = mock.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").respond(
            200, json={"id": "test", "object": "chat.completion", "created": 0,
                       "model": "qwen3.7-plus", "choices": [{"index": 0, "finish_reason": "stop",
                       "message": {"role": "assistant", "content": "{}"}}]})
        assert client.chat([{"role": "user", "content": "test"}], json_mode=True).content == "{}"
        body = json.loads(route.calls[0].request.content)
        assert body["model"] == "qwen3.7-plus"
        assert body["enable_thinking"] is False
        assert body["response_format"] == {"type": "json_object"}
