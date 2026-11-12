"""GoalAnalysis / ActionSuggest 两个 Subagent 的生产实现（LangChain create_agent，T15 验证路径）。

两个 Agent 使用显式传入的只读检索工具；不强制无必要的工具调用。
Subagent 失败向外抛（工作流节点按规则降级）；不静默吞错。
"""

from __future__ import annotations

import logging
import os

from .workflow import SubagentRunner

logger = logging.getLogger(__name__)


class LangChainSubagentRunner(SubagentRunner):
    def __init__(self, settings):
        self._settings = settings
        self._agents: dict[str, object] = {}
        self._context = None
        self.evidence = {}
        self.last_tool_calls = {}
        self.recorder = None

    def configure_context(self, personal, tracker, cancel_token=None):
        self._context = (personal, tracker, cancel_token)

    def tools_for(self, name):
        if self._context is None:
            return []
        from ..services.decision_tools import make_tools
        from ..services.cancel import check_cancel
        personal, tracker, token = self._context
        self.evidence[name] = []
        return make_tools(personal, name, tracker,
                          on_evidence=lambda rows: self.evidence[name].extend(rows),
                          cancel_check=lambda: check_cancel(token))

    def _build(self, name: str, tools: list):
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI

        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        model = ChatOpenAI(
            model=self._settings.dashscope_model,
            base_url=self._settings.dashscope_base_url,
            api_key=key,
            # SDK 将 extra_body 合并至实际顶层请求；保留原生工具循环，避免
            # LangChain 对 response_format 自动启用仅接受 strict tools 的解析入口。
            temperature=0, timeout=90, max_retries=2,
            extra_body={"enable_thinking": False, "response_format": {"type": "json_object"}},
        )
        from . import prompts
        system = prompts.GOAL_SYSTEM if name == "goal_analysis" else prompts.ADVICE_SYSTEM
        return create_agent(model, tools=tools, system_prompt=system)

    def run(self, name: str, prompt: str, tools: list) -> str:
        from openai import BadRequestError
        from time import perf_counter
        started = perf_counter()
        agent = self._build(name, tools)
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": prompt}]},
                                  config={"recursion_limit": 12})
        except BadRequestError as exc:
            from ..services.llm_router import json_mode_error_from
            converted = json_mode_error_from(exc, self._settings.dashscope_model)
            if converted is not None:
                logger.error("Subagent %s 所用模型 %s 不支持 JSON mode，请求显式失败",
                             name, self._settings.dashscope_model)
                raise converted from exc
            raise
        msgs = result.get("messages", [])
        self.last_tool_calls[name] = sum(len(getattr(m, "tool_calls", []) or []) for m in msgs)
        if self.recorder:
            from ..services.llm_router import ChatResult
            usage = [getattr(m, "usage_metadata", None) or {} for m in msgs]
            self.recorder(name, ChatResult(content="", input_tokens=sum(u.get("input_tokens", 0) for u in usage),
                output_tokens=sum(u.get("output_tokens", 0) for u in usage), elapsed_ms=int((perf_counter() - started) * 1000)),
                self._settings.dashscope_model, self._settings.dashscope_base_url)
        for m in reversed(msgs):
            content = getattr(m, "content", None)
            if (getattr(m, "type", None) == "ai" and not getattr(m, "tool_calls", [])
                    and isinstance(content, str) and content.strip()):
                from ..services.json_contract import parse_json_object
                parse_json_object(content)
                return content.strip()
        raise RuntimeError(f"{name} 无有效输出")
