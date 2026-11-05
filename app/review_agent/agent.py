"""每周回顾 Agent：LangGraph create_agent + 六个只读工具（阶段一）。

与微信 Agent（app/wechat_agent/agent.py）同一装配模式：
create_agent 完成 messages 状态、call_model/tools 节点与条件边。

系统提示词 = Agent 行为准则（改 docstring/提示词 = 改模型行为，须回归）。
只读保证：build_tools 只暴露读工具；统计数字来自确定性代码，提示词要求
模型直接引用、不臆造。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

SYSTEM_PROMPT = """你是个人每周回顾助手，通过只读工具读取用户的本地个人数据（每日任务、长期计划、随手备忘、重要信息、阅读记录），帮助用户回顾本周工作并规划下周。

工作规则：
1. 分析前先调用 get_task_stats 看本周任务全貌；需要核对具体任务时再调 get_week_tasks。
   统计工具返回的数字是代码计算的事实，直接引用，不要自己估算。
2. 分析目标推进时调 get_plans_overview；寻找搁置想法时调 get_memos_overview；
   参考个人原则/规则时调 get_important_infos（注意：重要信息是长期参考，不是当前待办）；
   分析阅读进展时调 get_reading_overview。
3. 任务"归属日期"和"完成时间"是两个概念：任务归属上周但本周完成，属于"清掉历史遗留"，
   不要误算成本周新增工作。完成时间为空的已完成任务是历史脏数据，统计中不算完成。
4. 跨模块关联（任务与长期目标是否相关、备忘是否值得转任务）是你的语义推断，
   必须明确说成"推断/可能相关"，不得说成数据库中存在的关联。
5. 信息不足时不要编造：向用户追问（例如某计划停滞的原因、某任务未完成的背景）。
   用户补充的信息优先于你的假设。
6. 你只负责分析和对话：生成下周建议、建议审核、周报确认由界面按钮触发，不要
   承诺"我已经保存/修改了任务"——你没有修改任何数据的权限，也不允许暗示已修改。
7. 所有回答用中文，简洁有条理；引用数据时给出具体数字和条目。
"""


def build_system_prompt(week_start: str, week_end: str) -> str:
    """注入本机当前日期与回顾周期（LLM 自身无法感知本地时钟）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return (
        f"今天是 {today}（本机系统日期）。本次回顾周期为 {week_start} 至 {week_end}"
        "（自然周，周一至周日）。\n\n" + SYSTEM_PROMPT
    )


def build_agent(session: Session, week_start: str, week_end: str, llm=None):
    """装配每周回顾 Agent。llm 可注入（测试用 FakeLLM）；为 None 时走统一出口 build_llm。"""
    from langchain.agents import create_agent

    from ..wechat_agent.llm_config import build_llm
    from .tools import build_tools

    model = (
        llm
        if llm is not None
        # stream_usage：让流式响应回传真实 token 用量（SSE 路径按轮落 token_usage）
        else build_llm(temperature=0.2, stream_usage=True)
    )
    tools = build_tools(session, week_start)
    return create_agent(
        model, tools, system_prompt=build_system_prompt(week_start, week_end)
    )
