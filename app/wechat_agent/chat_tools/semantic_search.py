"""语义检索工具：向量召回 + 基于消息 ID 的确定性回溯与统计。

工具集：
- semantic_search_messages   按语义检索聊天片段（RAG 召回）
- get_messages_by_ids        按消息 ID 取回原始记录（核对/补上下文）
- count_speakers_by_ids      按消息 ID 做发言人计数（确定性统计，服务
                             "参与讨论最多的人"类问题；按 ID 去重，
                             天然免疫 Chunk 重叠造成的重复计数）

注意：@tool 函数的 docstring 和参数签名会被 LangGraph 直接暴露给 LLM，
作为模型判断"何时调用本工具、传什么参数"的依据。改动 docstring = 改变模型行为。
"""

from __future__ import annotations

from datetime import datetime

from langchain_core.tools import tool

from ..normal_tools import rag_store

_MAX_IDS = 500  # 单次按 ID 查询的消息数上限，防注入超长列表


def _parse_ids(message_ids: str) -> list[str]:
    """把 "id1, id2 id3" 形式的 ID 列表解析为去重后的列表（保序）。

    消息 ID 是字符串（如 "message_8:Msg_...:240007"），不做 int 转换。
    """

    ids: list[str] = []
    for token in str(message_ids or "").replace(",", " ").split():
        if token not in ids:
            ids.append(token)
    return ids[:_MAX_IDS]


@tool
def semantic_search_messages(query: str, date: str = "", chat_id: str = "", top_k: int = 10) -> str:
    """按语义（含义）检索聊天记录，找出与问题意思相近的对话片段。

    适合"情绪、态度、观点、隐含表达"类问题——这类内容换个说法关键词就搜不到，
    例如"是否有人表达过对主播的担忧"可能表现为"早点休息""注意身体""状态不太好"。
    查确切名称、固定关键词、精确数量时不要用本工具，改用 search_messages/get_stats。

    Args:
        query: 自然语言检索问题，描述你想找的内容。
        date: 可选，限定日期 YYYY-MM-DD；留空搜索全部已索引日期。
        chat_id: 可选，限定群聊 ID（先用 list_chats 查询有哪些群）。
        top_k: 返回片段数，默认 10。

    返回：相关对话片段（含消息ID、时间、发言人），可按消息 ID 用
    get_messages_by_ids 取原文，或用 count_speakers_by_ids 统计参与人。
    """

    query = str(query or "").strip()
    if not query:
        return "query 不能为空。"
    date = str(date or "").strip()
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return f"date 格式应为 YYYY-MM-DD，收到: {date!r}"

    try:
        hits = rag_store.search(query, date=date, chat_id=str(chat_id or "").strip(), top_k=top_k)
    except Exception as exc:
        # Embedding/向量库异常不能让 Agent 崩溃：给出可操作的降级建议
        return (
            f"语义检索失败（{type(exc).__name__}: {exc}）。"
            "向量索引可能尚未构建，或 Embedding 服务暂不可用；"
            "可改用 search_messages 做关键词搜索。"
        )

    if not hits:
        return (
            "没有找到语义相关的内容。可能索引未构建或覆盖不到该日期，"
            "可先确认 list_chats，或改用 search_messages。"
        )

    parts = [f"找到 {len(hits)} 个语义相关片段（距离越小越相关）："]
    for index, hit in enumerate(hits, start=1):
        parts.append(
            f"--- 片段{index}（{hit['date']}，距离 {hit['distance']:.3f}）---\n{hit['text']}"
        )
    return "\n\n".join(parts)


@tool
def get_messages_by_ids(message_ids: str) -> str:
    """按消息 ID 列表从聊天库取回原始记录（自动去重，按时间排序）。

    用途：核对语义检索命中的具体消息、获取其完整上下文。
    消息 ID 可从 semantic_search_messages 返回的 "(#数字)" 标记中获得。

    Args:
        message_ids: 消息 ID 列表，逗号或空格分隔，例如 "12, 34 56"。
    """

    ids = _parse_ids(message_ids)
    if not ids:
        return "没有有效的消息 ID（应为逗号/空格分隔的消息 ID，如 message_8:Msg_xxx:240007）。"
    placeholders = ",".join("?" * len(ids))
    with rag_store._connect() as connection:
        rows = connection.execute(
            f"""SELECT message_id, time, sender, text FROM messages
                WHERE message_id IN ({placeholders}) ORDER BY timestamp""",
            ids,
        ).fetchall()
    if not rows:
        return f"聊天库中找不到这些消息 ID: {message_ids[:100]}"
    return "\n".join(
        f"[{row['time']}] {row['sender']}: {row['text']} (#{row['message_id']})" for row in rows
    )


@tool
def count_speakers_by_ids(message_ids: str) -> str:
    """按消息 ID 列表统计各发言人的消息条数（确定性代码统计，非估算）。

    适合"参与讨论最多的几个人""谁最活跃"类需要准确计数的场景：
    先由语义检索/人工判断挑出与问题相关的消息 ID，再用本工具计数。
    按消息 ID 去重，Chunk 重叠导致的重复 ID 不会影响结果；系统消息不计入。

    Args:
        message_ids: 相关消息 ID 列表，逗号或空格分隔。
    """

    ids = _parse_ids(message_ids)
    if not ids:
        return "没有有效的消息 ID（应为逗号/空格分隔的消息 ID，如 message_8:Msg_xxx:240007）。"
    placeholders = ",".join("?" * len(ids))
    with rag_store._connect() as connection:
        rows = connection.execute(
            f"""SELECT sender, count(*) AS n FROM messages
                WHERE message_id IN ({placeholders}) AND msg_type != '系统'
                GROUP BY sender ORDER BY n DESC""",
            ids,
        ).fetchall()
    if not rows:
        return "这些消息 ID 没有对应的发言人记录。"
    total = sum(row["n"] for row in rows)
    lines = [f"共 {total} 条消息来自 {len(rows)} 位发言人（已去重、排除系统消息）："]
    lines += [f"  {row['sender']}: {row['n']} 条" for row in rows]
    return "\n".join(lines)
