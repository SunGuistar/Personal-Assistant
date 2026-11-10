"""三个 Subagent 的生产实现（LangChain create_agent，T15 验证路径）。

技术研究/目标分析可带统一 RAG Tool；建议 Subagent 无工具（输入即上下文）。
Subagent 失败向外抛（工作流节点按规则降级）；不静默吞错。
"""

from __future__ import annotations

import logging
import os

from .workflow import SubagentRunner

logger = logging.getLogger(__name__)


class LangChainSubagentRunner(SubagentRunner):
    def __init__(self, settings, rag_tool=None):
        self._settings = settings
        self._rag = rag_tool
        self._agents: dict[str, object] = {}

    def _build(self, name: str, tools: list):
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI

        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        model = ChatOpenAI(
            model=self._settings.dashscope_model,
            base_url=self._settings.dashscope_base_url,
            api_key=key,
            temperature=0,
        )
        return create_agent(model, tools=tools)

    def run(self, name: str, prompt: str, tools: list) -> str:
        agent = self._agents.get(name)
        if agent is None:
            agent = self._build(name, tools)
            self._agents[name] = agent
        result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
        msgs = result.get("messages", [])
        for m in reversed(msgs):
            content = getattr(m, "content", None)
            if isinstance(content, str) and content.strip():
                return content.strip()
        raise RuntimeError(f"{name} 无有效输出")
