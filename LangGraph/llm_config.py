"""统一的 LLM 配置。

agent 决策与 summarizer 流水线共用同一个模型/key/endpoint，
改模型只需改本文件的 DEFAULT_MODEL，或在 .env 中设 DASHSCOPE_MODEL，
不再需要同时改 agent.py 和 summarizer.py 两处。
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

DEFAULT_MODEL = "qwen3.5-122b-a10b"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_TEMPERATURE = 0.2


def build_llm(**overrides) -> ChatOpenAI:
    """构造 DashScope（OpenAI 兼容模式）的 ChatOpenAI。

    参数优先级：调用方 overrides > .env 的 DASHSCOPE_MODEL > DEFAULT_MODEL。
    例如 summarizer 需要更大输出上限时：build_llm(max_tokens=8192)。
    """

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未找到 DASHSCOPE_API_KEY，请在 .env 中配置。")
    settings = {
        "model": os.environ.get("DASHSCOPE_MODEL", "").strip() or DEFAULT_MODEL,
        "api_key": api_key,
        "base_url": BASE_URL,
        "temperature": DEFAULT_TEMPERATURE,
    }
    settings.update(overrides)
    return ChatOpenAI(**settings)
