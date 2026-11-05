"""LLM 调用成本记录（token_usage 统一写入，AGENTS §6）。

回顾 Agent 的每次 LLM 调用（对话轮次 / 建议生成）都必须经此落库；
ref 约定 `weekly_review:chat:{review_id}` / `weekly_review:suggest:{review_id}`。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import TokenUsage


def extract_usage(messages: list) -> list[dict[str, int]]:
    """从 LangGraph 返回的 messages 中提取每次模型调用的用量（工具消息无用量，跳过）。

    注意：逐次"输入"包含当次对话历史，是累进值；各次加总才是实际计费量。
    """
    calls = []
    for message in messages:
        usage = getattr(message, "usage_metadata", None)
        if not usage:
            continue
        calls.append(
            {
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
            }
        )
    return calls


def record_usage(session: Session, llm: Any, response: Any, *, ref: str) -> None:
    """单次 LLM 调用的成本落 token_usage（参照 news_translation._record_usage 口径）。

    自带提交：作为独立的写操作不依赖调用方事务（API 流式场景无后续提交点）。
    """
    usage = getattr(response, "usage_metadata", None) or {}
    model = getattr(llm, "model_name", None) or getattr(llm, "model", None) or ""
    session.add(
        TokenUsage(
            kind="llm",
            model=str(model)[:64],
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cost_estimate=0.0,
            ref=ref[:128],
        )
    )
    session.commit()


def record_turn_usage(session: Session, calls: list[dict[str, int]], *, model: str, ref: str) -> None:
    """对话轮次的多次模型调用逐条落库（ref 相同，按行区分次数）。自带提交。"""

    for call in calls:
        session.add(
            TokenUsage(
                kind="llm",
                model=model[:64],
                input_tokens=call["input_tokens"],
                output_tokens=call["output_tokens"],
                cost_estimate=0.0,
                ref=ref[:128],
            )
        )
    session.commit()
