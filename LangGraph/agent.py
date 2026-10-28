"""微信群聊总结 Agent：LangGraph create_agent + 只读工具，仅分析不修改。

用法：
    python agent.py                          # 进入交互式问答
    python agent.py "总结2026-10-27这个群的聊天"   # 单轮提问

LLM 用 dashscope 的 qwen-plus（兼容 OpenAI 模式），Key 从仓库根目录 .env 读取。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "LangGraph"))

from dotenv import load_dotenv

load_dotenv(ROOT_DIR / ".env")

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from chat_tools import ALL_TOOLS

# 系统提示词 = Agent 的行为准则。其中"必须分时段多次取"这条最关键：
# 它替代了 wechat-chat-summary 里 chunking 模块的角色——不靠代码切分，
# 靠约束模型自己分批取数，从而把单次上下文体积控制在 token 预算内。
SYSTEM_PROMPT = """你是微信群聊天记录分析助手，通过工具读取本地聊天库，只进行分析，绝不修改任何数据。

工作规则：
1. 回答前先用 list_chats 确认库里有哪些群；涉及具体日期时先用 get_stats 看当天概况。
2. 一天的消息量可达数千条，单次读取会被工具限制在几百条。做全天总结时，按小时段分多次调用 get_messages（例如 0-5 点、6-11 点、12-17 点、18-23 点），先分别总结每个时段，最后汇总成完整总结。
3. 回答"谁说了什么/某话题"类问题时，用 search_messages 精确定位，不要全量翻消息。
4. 所有回答用中文；引用聊天内容时标注发言人昵称和大致时间；只基于工具返回的数据回答，不要编造库里不存在的内容。
"""


def build_agent():
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("未找到 DASHSCOPE_API_KEY，请在 .env 中配置。")
    model = ChatOpenAI(
        model="qwen-plus",
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0.2,  # 低温度：总结类任务求稳，减少发挥
    )
    # create_agent 一行完成状态图装配：内部定义 messages 状态、call_model/tools
    # 节点和"继续调工具还是结束"的条件边。langgraph 1.x 中该入口位于 langchain.agents，
    # 返回的仍是 LangGraph 编译好的图（CompiledStateGraph）。
    return create_agent(model, ALL_TOOLS, system_prompt=SYSTEM_PROMPT)


def _print_reply(result: dict) -> None:
    last = result["messages"][-1]
    print(f"\n{last.content}\n")


def _print_token_usage(messages: list) -> None:
    """汇总并打印本轮所有模型调用的 token 消耗（工具消息不带用量，跳过）。

    注意：逐次"输入"包含当次对话历史，是累进值；各次加总才是实际计费量。
    """

    calls = [
        usage
        for usage in (getattr(message, "usage_metadata", None) for message in messages)
        if usage
    ]
    if not calls:
        return
    print("Token 消耗：")
    total_in = total_out = 0
    for index, usage in enumerate(calls, start=1):
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        total_in += input_tokens
        total_out += output_tokens
        print(f"  第{index}次调用: 输入 {input_tokens} + 输出 {output_tokens} = {input_tokens + output_tokens}")
    print(f"  本轮合计: 输入 {total_in} + 输出 {total_out} = {total_in + total_out}")


def main() -> int:
    # token 消耗默认打印；--no-tokens 关闭
    show_tokens = "--no-tokens" not in sys.argv
    if not show_tokens:
        sys.argv.remove("--no-tokens")
    agent = build_agent()
    history: list = []
    if len(sys.argv) > 1:
        # 命令行带参数：单轮提问，答完即退（适合脚本化调用）
        question = " ".join(sys.argv[1:])
        result = agent.invoke({"messages": [HumanMessage(question)]})
        _print_reply(result)
        if show_tokens:
            _print_token_usage(result["messages"])
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
        result = agent.invoke({"messages": history})
        # invoke 返回的 messages 已包含本轮"模型决策→工具执行→结果回填"的完整
        # 往返记录，直接作为下一轮输入，即实现多轮追问的记忆能力。
        history = result["messages"]
        _print_reply(result)
        if show_tokens:
            _print_token_usage(result["messages"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
