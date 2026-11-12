"""模型路由：DeepSeek（正式，时段校验）/ DashScope（开发/手动主编），Token 落库。

规则（V0.6 §6.1 / V0.6.1 §6.1）：
- 正式自动晨报用 DeepSeek `deepseek-flash`；调用前检查允许时段（低谷），
  不在允许时段 → ModelNotAllowedError，**禁止静默切换模型**。
- 开发/手动重新生成用 DashScope `qwen3.7-plus`（OpenAI 兼容端点）。
- Thinking 按节点显式配置（deepseek-flash 默认开，显式关闭可降延迟/费用）。
- 所有请求强制 JSON mode；供应商返回不支持 json_object 的 400 报错时抛出
  JsonModeUnsupportedError，禁止静默关闭 JSON mode 或回退纯文本。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from openai import BadRequestError
from langchain_openai import ChatOpenAI

from ..models import TokenUsage

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))
PEAK_WINDOWS_UTC = ((1, 4), (6, 10))


class ModelNotAllowedError(RuntimeError):
    """正式模型不在允许时段（或配置缺失），必须阻塞，不得切换其他模型。"""


class JsonModeUnsupportedError(RuntimeError):
    """模型不支持 JSON mode（json_object）。

    禁止静默关闭 JSON mode 重试或回退纯文本；必须显式失败，由调用方走
    降级/阻塞流程，并在错误信息中指明需更换支持 JSON mode 的模型。
    """


_JSON_MODE_MARKERS = ("json_object", "json mode", "structured output", "structured_output")


def json_mode_error_from(exc: BadRequestError, model: str) -> JsonModeUnsupportedError | None:
    """供应商 400 报错命中 JSON mode 不支持特征时返回显式领域错误，否则返回 None。"""

    message = str(exc).lower()
    if not (any(marker in message for marker in _JSON_MODE_MARKERS)
            or ("not support" in message and "format" in message)):
        return None
    return JsonModeUnsupportedError(
        f"模型 {model} 不支持 JSON mode（json_object），请更换支持 JSON mode 的模型；"
        f"禁止静默关闭 JSON mode 或回退纯文本。供应商报错摘要：{str(exc)[:200]}")


def is_allowed_period(now_cst: datetime | None = None,
                      holidays: set[str] | None = None) -> tuple[bool, str]:
    """工作日高峰（北京 09-12、14-18）之外为允许时段；周末/节假日全天允许。"""

    now = now_cst or datetime.now(CST)
    day = now.date().isoformat()
    if now.weekday() >= 5 or (holidays and day in holidays):
        return True, "off-peak(weekend/holiday)"
    now_utc = now.astimezone(timezone.utc)
    for start, end in PEAK_WINDOWS_UTC:
        if start <= now_utc.hour < end:
            return False, f"peak UTC {start:02d}:00-{end:02d}:00"
    return True, "off-peak(weekday)"


@dataclass
class ChatResult:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int | None = None
    cache_miss_tokens: int | None = None
    tool_calls: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0


class ChatClient:
    """主编普通 ChatOpenAI 节点适配；沿用 ChatResult 契约与 LangGraph 回调上下文。"""

    def __init__(self, base_url: str, api_key_env: str, model: str,
                 thinking: bool = False, timeout: float = 120.0):
        key = os.environ.get(api_key_env, "").strip()
        if not key:
            raise ModelNotAllowedError(f"{api_key_env} 未配置")
        self._client = ChatOpenAI(model=model, base_url=base_url, api_key=key,
            temperature=0, timeout=timeout, max_retries=2, use_responses_api=False)
        self.model = model
        self.thinking = thinking
        self.base_url = base_url

    def chat(self, messages: list[dict], *, json_mode: bool = True,
             tools: list[dict] | None = None, thinking: bool | None = None) -> ChatResult:
        if json_mode is not True:
            raise ValueError("晨报 LLM 调用必须启用 JSON mode")
        extra_body: dict = {"response_format": {"type": "json_object"}}
        use_thinking = self.thinking if thinking is None else thinking
        if "deepseek" in self.base_url:
            extra_body["chat_template_kwargs"] = {"thinking": bool(use_thinking)}
        if "dashscope" in self.base_url:
            extra_body["enable_thinking"] = bool(use_thinking)
        kwargs: dict = {"extra_body": extra_body}
        if tools:
            kwargs["tools"] = tools
        t0 = time.perf_counter()
        try:
            # invoke 自动继承 LangGraph 的 callbacks；asyncio.to_thread 保留其上下文。
            # 只新增模型子运行，不创建 Agent，也不在追踪回调中重复写 TokenUsage。
            msg = self._client.invoke(messages,
                config={"run_name": "editor_model", "tags": ["morning-report", "editor"],
                        "metadata": {"mr_node": "editor"}}, **kwargs)
        except BadRequestError as exc:
            converted = json_mode_error_from(exc, self.model)
            if converted is not None:
                logger.error("模型 %s 不支持 JSON mode（json_object），请求显式失败", self.model)
                raise converted from exc
            raise
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if not isinstance(msg.content, str):
            raise ValueError("主编模型必须返回字符串 JSON 内容")
        usage = msg.usage_metadata or {}
        raw_usage = msg.response_metadata.get("token_usage") or {}
        input_tokens = usage.get("input_tokens", raw_usage.get("prompt_tokens", 0)) or 0
        output_tokens = usage.get("output_tokens", raw_usage.get("completion_tokens", 0)) or 0
        cache_hits = raw_usage.get("prompt_cache_hit_tokens")
        if cache_hits is None:
            cache_hits = (usage.get("input_token_details") or {}).get("cache_read")
        cache_misses = raw_usage.get("prompt_cache_miss_tokens")
        if cache_misses is None and cache_hits is not None:
            cache_misses = max(0, input_tokens - cache_hits)
        return ChatResult(
            content=msg.content, input_tokens=input_tokens, output_tokens=output_tokens,
            cache_hit_tokens=cache_hits, cache_miss_tokens=cache_misses,
            tool_calls=[{"name": tc["name"], "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False)}
                        for tc in msg.tool_calls], elapsed_ms=elapsed_ms,
        )


def record_usage(mr, run_id: int | None, node: str, client: ChatClient,
                 result: ChatResult, allowed: str = "unknown") -> None:
    """Token/耗时/费用字段落库（V0.6.1 §6.3）；缺字段记 None 而非 0。"""

    mr.add(TokenUsage(
        run_id=run_id, node=node,
        provider="deepseek" if "deepseek" in client.base_url else "dashscope",
        model=client.model,
        input_tokens=result.input_tokens or None,
        output_tokens=result.output_tokens or None,
        cache_hit_tokens=result.cache_hit_tokens,
        cache_miss_tokens=result.cache_miss_tokens,
        elapsed_ms=result.elapsed_ms,
        cost_usd=None,  # 价格随官方调整，展示侧按 price tier 估算；不臆造
        price_tier=allowed,
    ))
    mr.commit()


def formal_client(settings) -> ChatClient:
    """正式模型（调用前必须已通过 is_allowed_period 校验）。"""

    ok, reason = is_allowed_period()
    if not ok:
        raise ModelNotAllowedError(f"当前处于模型禁止时段（{reason}），不自动切换其他模型")
    return ChatClient(settings.deepseek_base_url, "DEEPSEEK_API_KEY",
                      settings.deepseek_model, thinking=False)


def dev_client(settings) -> ChatClient:
    return ChatClient(settings.dashscope_base_url, "DASHSCOPE_API_KEY",
                      settings.dashscope_model, thinking=False)
