"""终端输出与问答落盘：回答打印、Token 消耗统计、API 错误提示、耗时记录。

从 agent.py 迁出：主流程只负责编排，人机交互相关的打印统一收敛到这里。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def save_reply(question: str, reply: str) -> Path:
    """把本轮问答追加到 Output/Agent问答_<日期>.md，返回文件路径。

    文件按天聚合、追加写入，首次创建时补标题；回答本身是 LLM 生成的
    Markdown 文本，直接嵌入即可。
    """

    md_path = ROOT_DIR / "Output" / f"Agent问答_{datetime.now():%Y-%m-%d}.md"
    if not md_path.exists():
        md_path.write_text("# 微信群聊总结 Agent 问答记录\n", encoding="utf-8")
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(f"\n## {datetime.now():%H:%M:%S}\n\n**问:** {question}\n\n{reply}\n")
    return md_path


def print_reply(result: dict, question: str | None = None) -> None:
    """打印本轮回答；单轮模式下顺带把问答落盘并提示文件路径。"""

    last = result["messages"][-1]
    print(f"\n{last.content}\n")
    if question is not None:
        print(f"已保存到: {save_reply(question, last.content)}")


def record_total(elapsed_text: str) -> None:
    """会话结束时的总耗时：打印到终端，并追加到当天问答记录文件尾部。

    当天文件不存在（没有成功保存过回答）时只打印到终端。
    """

    text = f"总耗时: {elapsed_text}"
    print(f"\n{text}")
    md_path = ROOT_DIR / "Output" / f"Agent问答_{datetime.now():%Y-%m-%d}.md"
    if md_path.exists():
        with open(md_path, "a", encoding="utf-8") as f:
            f.write(f"\n---\n\n**{text}**\n")


def print_token_usage(messages: list) -> None:
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


def print_api_error(exc: Exception) -> bool:
    """把模型 API 异常（额度/限流/网络）转成人话提示，返回 True 表示已处理。

    Agent 主链路的 model 节点不在任何工具内部，LLM 异常会直接穿透 invoke
    抛到 main——这里统一兜住，避免原始 traceback 刷屏。
    """

    # 注意：LengthFinishReasonError / ContentFilterFinishReasonError 直接继承
    # openai.OpenAIError 而非 APIError，必须显式判断，并用 OpenAIError 做总闸。
    from openai import (
        APIConnectionError,
        APITimeoutError,
        ContentFilterFinishReasonError,
        LengthFinishReasonError,
        OpenAIError,
        PermissionDeniedError,
        RateLimitError,
    )

    if isinstance(exc, PermissionDeniedError):
        print("\n模型 API 额度已用完（403）。请到阿里云百炼控制台充值或关闭\"仅使用免费额度\"后重试。\n")
    elif isinstance(exc, RateLimitError):
        print("\n模型 API 限流中，请稍等片刻后重试。\n")
    elif isinstance(exc, (APIConnectionError, APITimeoutError)):
        print("\n模型 API 网络连接失败，请检查网络后重试。\n")
    elif isinstance(exc, LengthFinishReasonError):
        # 服务器返回 200 但输出被长度上限截断，JSON 解析失败
        print("\n模型输出超长被截断（JSON 不完整），请重试。\n")
    elif isinstance(exc, ContentFilterFinishReasonError):
        print("\n模型输出触发内容审核被截断，请调整输入后重试。\n")
    elif isinstance(exc, OpenAIError):
        # 总闸：兜住 openai 库里尚未单独处理的所有异常（含 APIError 家族）
        print(f"\n模型 API 返回错误（HTTP {getattr(exc, 'status_code', '?')}），请稍后重试。\n")
    else:
        return False
    return True
