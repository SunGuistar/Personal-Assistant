"""统一的 LLM 配置。

配置项集中在同目录的 llm_config.json（模型/base_url/温度/JSON mode 名单），
改配置只需改 JSON 文件。环境变量 DASHSCOPE_MODEL 仍可临时覆盖模型名，
DASHSCOPE_API_KEY 仍从 .env 读取（敏感信息不进 JSON）。
"""

from __future__ import annotations

import json
import os
import re
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


# 依据：百炼官方"JSON Object 支持情况"清单。标注"（非思考模式）"的系列仅在
# 非思考模式下支持结构化输出，调用时需附加 enable_thinking=False。
# 官方清单更新时维护这两个常量（正则，re.match 从开头匹配）。
# 注意 qwen3-(?!coder) 的 (?!...) 是负向预查：Qwen3 开源系列要关思考，
# 而 Qwen3-Coder 原生支持、必须排除。
_JSON_MODE_NATIVE_PATTERNS = (
    r"qwen3\.8-omni",
    r"qwen3\.5-omni",
    r"qwen3-coder",
    r"qwen3\.8",
    r"qwen3\.7",
    r"qwen-long",
    r"qwen2\.5",
)
_JSON_MODE_DISABLE_THINKING_PATTERNS = (
    "qwen-max",
    "qwen3-max",
    r"qwen3\.6-max",
    "qwen-plus",
    r"qwen3\.6-plus",
    r"qwen3\.5-plus",
    "qwen-flash",
    r"qwen3\.6-flash",
    r"qwen3\.5-flash",
    "qwen-turbo",
    "qwen-vl",
    "qwen3-vl",
    r"qwen3\.6-",
    r"qwen3\.5-",
    r"qwen3-(?!coder)",
)


@lru_cache(maxsize=1)
def _compiled_patterns() -> tuple[tuple[re.Pattern, ...], tuple[re.Pattern, ...]]:
    return (
        tuple(re.compile(p) for p in _JSON_MODE_NATIVE_PATTERNS),
        tuple(re.compile(p) for p in _JSON_MODE_DISABLE_THINKING_PATTERNS),
    )


def should_disable_thinking(model_name: str) -> bool:
    """判断该模型在 JSON Mode 下是否需要关闭思考模式。

    - 命中原生支持名单（_JSON_MODE_NATIVE_PATTERNS）→ False（不加参数）；
    - 命中"（非思考模式）"名单（_JSON_MODE_DISABLE_THINKING_PATTERNS）→ True；
    - 都不命中的未知模型 → False（保守不加，沿用模型默认行为）。

    原生名单优先判断，用于排除 qwen3-coder、qwen3.5-omni 等同前缀例外。
    """

    name = model_name.lower().strip()
    native, disable = _compiled_patterns()
    if any(p.match(name) for p in native):
        return False
    if any(p.match(name) for p in disable):
        return True
    return False


def get_json_mode_kwargs(llm: ChatOpenAI) -> dict[str, Any]:
    """根据当前模型能力，生成 JSON Mode 所需的额外参数（思考模式的开关）。"""

    if should_disable_thinking(get_llm_model_name(llm)):
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
