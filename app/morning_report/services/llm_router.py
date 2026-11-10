"""模型路由：DeepSeek（正式，时段校验）/ DashScope（开发与质量评价），Token 落库。

规则（V0.6 §6.1 / V0.6.1 §6.1）：
- 正式自动晨报用 DeepSeek `deepseek-flash`；调用前检查允许时段（低谷），
  不在允许时段 → ModelNotAllowedError，**禁止静默切换模型**。
- 开发/手动重新生成与质量评价用 DashScope `qwen-flash`（OpenAI 兼容端点）。
- Thinking 按节点显式配置（deepseek-flash 默认开，显式关闭可降延迟/费用）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from openai import OpenAI

from ..models import TokenUsage

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))
PEAK_WINDOWS_UTC = ((1, 4), (6, 10))


class ModelNotAllowedError(RuntimeError):
    """正式模型不在允许时段（或配置缺失），必须阻塞，不得切换其他模型。"""


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
    """OpenAI 兼容端点封装（DeepSeek / DashScope 同构）。"""

    def __init__(self, base_url: str, api_key_env: str, model: str,
                 thinking: bool = False, timeout: float = 120.0):
        key = os.environ.get(api_key_env, "").strip()
        if not key:
            raise ModelNotAllowedError(f"{api_key_env} 未配置")
        self._client = OpenAI(base_url=base_url, api_key=key, timeout=timeout)
        self.model = model
        self.thinking = thinking
        self.base_url = base_url

    def chat(self, messages: list[dict], *, json_mode: bool = False,
             tools: list[dict] | None = None, thinking: bool | None = None) -> ChatResult:
        kwargs: dict = {"model": self.model, "messages": messages, "temperature": 0}
        use_thinking = self.thinking if thinking is None else thinking
        if "deepseek" in self.base_url:
            # V4.1 Flash：thinking 默认开，显式关闭传 chat_template_kwargs
            kwargs["chat_template_kwargs"] = {"thinking": bool(use_thinking)}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if tools:
            kwargs["tools"] = tools
        t0 = time.perf_counter()
        resp = self._client.chat.completions.create(**kwargs)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        msg = resp.choices[0].message
        usage = resp.usage
        return ChatResult(
            content=msg.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cache_hit_tokens=getattr(usage, "prompt_cache_hit_tokens", None),
            cache_miss_tokens=getattr(usage, "prompt_cache_miss_tokens", None),
            tool_calls=[
                {"name": tc.function.name, "arguments": tc.function.arguments}
                for tc in (msg.tool_calls or [])
            ],
            elapsed_ms=elapsed_ms,
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
