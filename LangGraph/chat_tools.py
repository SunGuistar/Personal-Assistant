"""只读工具集：供 LangGraph Agent 查询归一化聊天库。

所有工具只读（sqlite3 以 mode=ro 打开），不提供任何修改/导出能力。
数据库位置默认为 GetWechatInfo/DataInfo/chat_snapshot_normalized.sqlite3，
可用环境变量 WECHAT_AGENT_DB 覆盖。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "GetWechatInfo" / "DataInfo" / "chat_snapshot_normalized.sqlite3"
)


def _db_path() -> Path:
    configured = os.environ.get("WECHAT_AGENT_DB", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if not path.exists():
        raise RuntimeError(f"找不到归一化聊天库 {path}，请先运行 normalize_snapshot.py。")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _day_range(date: str) -> tuple[int, int]:
    day = datetime.strptime(date.strip(), "%Y-%m-%d")
    start = int(day.replace(hour=0, minute=0, second=0).timestamp())
    end = int(day.replace(hour=23, minute=59, second=59).timestamp())
    return start, end


def _rows_to_lines(rows: list[sqlite3.Row]) -> str:
    return "\n".join(f"[{row['time']}] {row['sender']}: {row['text']}" for row in rows)


@tool
def list_chats() -> str:
    """列出聊天库里有哪些群以及消息总数。回答任何问题前先用它确认有哪些数据。"""

    with _connect() as connection:
        rows = connection.execute(
            "SELECT chat_id, display_name FROM chats ORDER BY display_name"
        ).fetchall()
        counts = {
            row["chat_id"]: row["n"]
            for row in connection.execute(
                "SELECT chat_id, count(*) AS n FROM messages GROUP BY chat_id"
            )
        }
    if not rows:
        return "聊天库为空。"
    return "\n".join(
        f"{row['display_name']} ({row['chat_id']}): {counts.get(row['chat_id'], 0)} 条消息"
        for row in rows
    )


@tool
def get_stats(date: str) -> str:
    """获取指定日期这一天的聊天概况统计（总消息数、各类型数量、发言最多的成员）。

    Args:
        date: 日期，格式 YYYY-MM-DD，例如 2026-10-27。
    """

    start, end = _day_range(date)
    with _connect() as connection:
        total = connection.execute(
            "SELECT count(*) FROM messages WHERE timestamp >= ? AND timestamp <= ?",
            (start, end),
        ).fetchone()[0]
        by_type = connection.execute(
            """SELECT msg_type, count(*) AS n FROM messages
               WHERE timestamp >= ? AND timestamp <= ? GROUP BY msg_type ORDER BY n DESC""",
            (start, end),
        ).fetchall()
        by_sender = connection.execute(
            """SELECT sender, count(*) AS n FROM messages
               WHERE timestamp >= ? AND timestamp <= ? AND msg_type != '系统'
               GROUP BY sender ORDER BY n DESC LIMIT 10""",
            (start, end),
        ).fetchall()
    if not total:
        return f"{date} 没有消息记录。"
    lines = [f"{date} 共 {total} 条消息。"]
    lines.append("类型分布: " + "、".join(f"{row['msg_type']} {row['n']}" for row in by_type))
    lines.append(
        "发言排行: " + "、".join(f"{row['sender']}({row['n']})" for row in by_sender)
    )
    return "\n".join(lines)


@tool
def get_messages(date: str, start_hour: int = 0, end_hour: int = 23, limit: int = 500) -> str:
    """按日期和小时段读取消息原文，返回格式化聊天记录（每行 '[MM-DD HH:MM] 发送者: 正文'）。
    一天消息量很大时必须分多次调用本工具（每次只取几个小时），不要试图一次读全天。

    Args:
        date: 日期，格式 YYYY-MM-DD。
        start_hour: 开始小时（含），0-23，默认 0。
        end_hour: 结束小时（含），0-23，默认 23。
        limit: 最多返回条数，默认 500，最大 1000。
    """

    day = datetime.strptime(date.strip(), "%Y-%m-%d")
    start = int(day.replace(hour=max(0, min(23, start_hour)), minute=0, second=0).timestamp())
    end = int(day.replace(hour=max(0, min(23, end_hour)), minute=59, second=59).timestamp())
    limit = max(1, min(int(limit), 1000))
    with _connect() as connection:
        rows = connection.execute(
            """SELECT time, sender, text FROM messages
               WHERE timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp LIMIT ?""",
            (start, end, limit),
        ).fetchall()
    if not rows:
        return f"{date} {start_hour}:00-{end_hour}:59 没有消息。"
    return f"{date} {start_hour}:00-{end_hour}:59 共 {len(rows)} 条：\n" + _rows_to_lines(rows)


@tool
def search_messages(keyword: str, date: str = "", limit: int = 30) -> str:
    """按关键词搜索消息正文，返回匹配的聊天记录。适合回答"谁说了某话题"类问题。

    Args:
        keyword: 要搜索的关键词。
        date: 可选，限定日期 YYYY-MM-DD；留空搜索全部日期。
        limit: 最多返回条数，默认 30。
    """

    keyword = str(keyword or "").strip()
    if not keyword:
        return "关键词不能为空。"
    like = f"%{keyword}%"
    limit = max(1, min(int(limit), 100))
    clauses = "text LIKE ?"
    params: list = [like]
    if date.strip():
        start, end = _day_range(date)
        clauses += " AND timestamp >= ? AND timestamp <= ?"
        params += [start, end]
    params.append(limit)
    with _connect() as connection:
        rows = connection.execute(
            f"""SELECT time, sender, text FROM messages
                WHERE {clauses} ORDER BY timestamp LIMIT ?""",
            params,
        ).fetchall()
    if not rows:
        return f"没有找到包含 {keyword!r} 的消息。"
    return f"找到 {len(rows)} 条包含 {keyword!r} 的消息：\n" + _rows_to_lines(rows)


ALL_TOOLS = [list_chats, get_stats, get_messages, search_messages]
