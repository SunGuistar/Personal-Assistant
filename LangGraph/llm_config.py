"""统一的 LLM 配置。

配置项集中在同目录的 llm_config.json（模型/base_url/温度/JSON mode 名单），
改配置只需改 JSON 文件。环境变量 DASHSCOPE_MODEL 仍可临时覆盖模型名，
DASHSCOPE_API_KEY 仍从 .env 读取（敏感信息不进 JSON）。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI

_CONFIG_PATH = Path(__file__).resolve().parent / "llm_config.json"


@lru_cache(maxsize=1)
def _load_config() -> dict[str, Any]:
    """读取并缓存 llm_config.json。文件缺失/格式错误时给出明确报错。"""

    try:
        config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"找不到 LLM 配置文件: {_CONFIG_PATH}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM 配置文件不是合法 JSON: {_CONFIG_PATH} ({exc})")
    if not isinstance(config, dict) or not config.get("default_model"):
        raise RuntimeError(f"LLM 配置文件缺少 default_model 字段: {_CONFIG_PATH}")
    return config


def get_model_name() -> str:
    """获取当前使用的模型名称（环境变量优先于 JSON 配置）。"""

    return (
        os.environ.get("DASHSCOPE_MODEL", "").strip()
        or _load_config()["default_model"]
    )


def get_llm_model_name(llm: ChatOpenAI) -> str:
    """获取当前 LLM 实例实际使用的模型名称。"""

    return (
        getattr(llm, "model_name", None)
        or getattr(llm, "model", None)
        or get_model_name()
    )


def get_json_mode_kwargs(llm: ChatOpenAI) -> dict[str, Any]:
    """根据当前模型能力，生成 JSON Mode 所需的额外参数。

    名单中的模型（思维链与 JSON 输出并存会偶发抽风）：
        关闭思考模式。

    其他模型：
        不额外传递模型专属参数。
    """

    model_name = get_llm_model_name(llm).lower().strip()
    disabled = _load_config().get("json_mode_disable_thinking_models", [])

    if model_name in {m.lower().strip() for m in disabled}:
        return {
            "extra_body": {
                "enable_thinking": False
            }
        }

    return {}


def build_llm(**overrides) -> ChatOpenAI:
    """构造 DashScope（OpenAI 兼容模式）的 ChatOpenAI。

    参数优先级：
        调用方 overrides > .env DASHSCOPE_MODEL > llm_config.json

    例如：
        build_llm(max_tokens=8192)
    """

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "未找到 DASHSCOPE_API_KEY，请在 .env 中配置。"
        )

    config = _load_config()
    settings = {
        "model": get_model_name(),
        "api_key": api_key,
        "base_url": config["base_url"],
        "temperature": config.get("default_temperature", 0.2),
    }

    settings.update(overrides)

    return ChatOpenAI(**settings)
