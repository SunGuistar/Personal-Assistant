"""微信群聊总结 Agent：LangGraph create_agent + 只读工具，仅分析不修改。

用法：
    python agent.py                          # 进入交互式问答
    python agent.py "总结2026-10-27这个群的聊天"   # 单轮提问

LLM 配置统一在 llm_config.py（模型/key/endpoint 一处维护），Key 从仓库根目录 .env 读取。
终端打印、问答落盘、Token 统计、API 错误提示等输出逻辑在
Normal_Tools/console_output.py 中维护。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

load_dotenv(ROOT_DIR / ".env")

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from LangGraph.Chat_tools.chat_tools import ALL_TOOLS
from LangGraph.llm_config import build_llm
from LangGraph.Normal_Tools.console_output import (
    print_api_error,
    print_reply,
    print_token_usage,
    record_total,
)
from LangGraph.Normal_Tools.time_utils import SessionTimer
from LangGraph.Normal_Tools.tracing_config import configure_tracing

configure_tracing()  # 收敛 langsmith 报错日志、增强后台上传重试，须在首次追踪前调用

# 系统提示词 = Agent 的行为准则。其中"必须分时段多次取"这条最关键：
# 它替代了 wechat-chat-summary 里 chunking 模块的角色——不靠代码切分，
# 靠约束模型自己分批取数，从而把单次上下文体积控制在 token 预算内。
SYSTEM_PROMPT = """你是微信群聊天记录分析助手，通过工具读取本地聊天库，只进行分析，绝不修改任何数据。

工作规则：
1. 回答前先用 list_chats 确认库里有哪些群；涉及具体日期时先用 get_stats 看当天概况。
2. 一天的消息量可达数千条，单次读取会被工具限制在几百条。做全天总结时，按小时段分多次调用 get_messages（例如 0-5 点、6-11 点、12-17 点、18-23 点），先分别总结每个时段，最后汇总成完整总结。
3. 回答"谁说了什么/某话题"类问题时，不要全量翻消息：内容涉及确切名称、固定说法的
   用 search_messages 精确定位；涉及情绪、态度、观点、隐含表达等语义内容的用
   semantic_search_messages。
4. 用户要求"总结/日报/回顾"某天聊天时，必须调用 summarize_chat 工具生成报告（HTML/PNG 文件），
   不要自己用 get_messages 逐片阅读；拿到路径后告知用户文件位置并给出简要概括。
5. 两种检索方式二选一，不要叠加：已用 semantic_search_messages 检索的问题，不再用
   search_messages 做关键词精确搜索（仅当语义检索明确返回"没有找到"时，才改用
   search_messages 兜底一次）；反之，关键词能解决的问题不要再用语义检索。
6. 需要统计"参与讨论最多的人/各发言人次数"时，不要凭检索片段自己数：先从相关
   片段中挑出与问题相关的消息 ID，再用 count_speakers_by_ids 做确定性统计；
   核对具体消息原文用 get_messages_by_ids，缺上下文再用 get_messages 按时段补读。
7. 所有回答用中文；引用聊天内容时标注发言人昵称和大致时间；只基于工具返回的数据回答，不要编造库里不存在的内容。
"""


def build_system_prompt() -> str:
    """组装系统提示词：注入本机当前日期。

    LLM 自身无法访问运行环境的时钟，对"今天/昨天"的认知只能来自提示词
    或服务商注入的日期（后者可能因时区/网关与本地不一致）。把本机日期
    明确写进提示词，相对日期计算才以用户机器为准。
    """

    today = datetime.now().strftime("%Y-%m-%d")
    date_line = (
        f"今天是 {today}（本机系统日期）。用户提问中的"
        "'今天/昨天/明天/这周/上周五'等相对日期，都基于这个日期推算；"
        "不要依赖你自己的时间感知。\n\n"
    )
    return date_line + SYSTEM_PROMPT


def build_agent():
    # 模型/key/endpoint 统一由 llm_config.build_llm 提供，低温度：总结类任务求稳，减少发挥
    model = build_llm()
    # create_agent 一行完成状态图装配：内部定义 messages 状态、call_model/tools
    # 节点和"继续调工具还是结束"的条件边。langgraph 1.x 中该入口位于 langchain.agents，
    # 返回的仍是 LangGraph 编译好的图（CompiledStateGraph）。
    return create_agent(model, ALL_TOOLS, system_prompt=build_system_prompt())


def main() -> int:
    timer = SessionTimer()
    # token 消耗默认打印；--no-tokens 关闭
    show_tokens = "--no-tokens" not in sys.argv
    if not show_tokens:
        sys.argv.remove("--no-tokens")
    agent = build_agent()
    history: list = []
    if len(sys.argv) > 1:
        # 命令行带参数：单轮提问，答完即退（适合脚本化调用）
        question = " ".join(sys.argv[1:])
        try:
            result = agent.invoke({"messages": [HumanMessage(question)]})
        except Exception as exc:
            if not print_api_error(exc):
                raise
            record_total(timer.elapsed_text())
            return 1
        print_reply(result, question)
        if show_tokens:
            print_token_usage(result["messages"])
        record_total(timer.elapsed_text())
        return 0
    print("微信群聊总结 Agent（输入 exit 退出）")
    while True:
        try:
            question = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question in {"exit", "quit"}:
            break
        history.append(HumanMessage(question))
        try:
            result = agent.invoke({"messages": history})
        except Exception as exc:
            if not print_api_error(exc):
                raise
            continue  # 会话保活，等用户换问题或稍后重试
        # invoke 返回的 messages 已包含本轮"模型决策→工具执行→结果回填"的完整
        # 往返记录，直接作为下一轮输入，即实现多轮追问的记忆能力。
        history = result["messages"]
        print_reply(result, question)
        if show_tokens:
            print_token_usage(result["messages"])
    record_total(timer.elapsed_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
