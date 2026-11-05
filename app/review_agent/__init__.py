"""每周回顾 Agent 包（阶段一）。

- tools.py：六个只读工具（build_tools 工厂，绑定会话与周期）
- agent.py：LangGraph create_agent 装配与系统提示词

设计边界（已批准原则）：单 Agent、只读分析、多轮对话；
建议的生成/审核/确认走 review_service 状态机，不经由 Agent 工具——
Agent 没有写工具，机制上无法修改任何业务数据或周报状态。
"""

from .agent import build_agent

__all__ = ["build_agent"]
