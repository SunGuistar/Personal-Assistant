"""微信两库的清理访问层（独立于 Agent 只读通道）。

背景约束：
- 归一化库在 Agent/RAG 层一律 `mode=ro` 打开（只读硬约束）；
- 清理是独立的管理通道：本模块用**单独的读写连接**执行候选日期范围内的删除，
  绝不影响只读通道；删除范围经 protection 规则与执行前复检双重约束；
- 原始快照库由本项目自行管理（同步时写入），WeChatDataAnalysis 原始库不触碰。

所有函数接受显式路径，便于隔离测试；默认路径与现有模块常量保持一致。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from ..wechat_agent.data_api.message_store import DEFAULT_DB_PATH as SNAPSHOT_DB_PATH

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def normalized_db_path() -> Path:
    """与 rag_store/chat_tools 同一环境变量约定（WECHAT_AGENT_DB 优先）。"""

    configured = os.environ.get("WECHAT_AGENT_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return ROOT_DIR / "GetWechatInfo" / "DataInfo" / "chat_snapshot_normalized.sqlite3"


def connect_rw(path: Path) -> sqlite3.Connection:
    """清理专用读写连接（独立于 Agent 的 mode=ro 通道）。"""

    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def scan_message_groups(
    connection: sqlite3.Connection,
    *,
    table: str,
    ts_column: str,
    text_column: str | None = None,
) -> dict[tuple[str, str], dict]:
    """按 (chat_id, 本地日期) 分组统计消息。只读扫描，无副作用。

    返回 {(chat_id, date): {"count", "min_ts", "max_ts", "size"}}
    日期换算在 Python 侧按 Asia/Shanghai 做（不用 SQLite 时区修饰符，避免口径漂移）。
    """

    from .protection import date_of_ts

    text_expr = f", {text_column} as txt" if text_column else ", null as txt"
    rows = connection.execute(
        f"select chat_id, {ts_column} as ts{text_expr} from {table}"  # noqa: S608 （表名/列名为内部常量）
    ).fetchall()
    groups: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["chat_id"], date_of_ts(row["ts"]))
        bucket = groups.setdefault(
            key, {"count": 0, "min_ts": row["ts"], "max_ts": row["ts"], "size": 0}
        )
        bucket["count"] += 1
        bucket["min_ts"] = min(bucket["min_ts"], row["ts"])
        bucket["max_ts"] = max(bucket["max_ts"], row["ts"])
        if row["txt"]:
            bucket["size"] += len(row["txt"])
    return groups


def count_range(
    connection: sqlite3.Connection, table: str, chat_id: str, start: int, end: int, *, ts_column: str = "timestamp"
) -> int:
    """[start, end) 时间区间内的消息数（执行前/执行后一致性校验用）。"""

    return int(
        connection.execute(
            f"select count(*) from {table} where chat_id = ? and {ts_column} >= ? and {ts_column} < ?",  # noqa: S608
            (chat_id, start, end),
        ).fetchone()[0]
    )


def delete_range(
    connection: sqlite3.Connection, table: str, chat_id: str, start: int, end: int, *, ts_column: str = "timestamp"
) -> int:
    """删除 [start, end) 区间内该群消息，返回删除行数。"""

    cursor = connection.execute(
        f"delete from {table} where chat_id = ? and {ts_column} >= ? and {ts_column} < ?",  # noqa: S608
        (chat_id, start, end),
    )
    connection.commit()
    return int(cursor.rowcount)


def fetch_ts_map(connection: sqlite3.Connection, message_ids: list[str]) -> dict[str, int]:
    """message_id → timestamp（chunk 归属判定用；只读）。"""

    if not message_ids:
        return {}
    placeholders = ",".join("?" for _ in message_ids)
    rows = connection.execute(
        f"select message_id, timestamp from messages where message_id in ({placeholders})",  # noqa: S608
        message_ids,
    ).fetchall()
    return {row["message_id"]: int(row["timestamp"]) for row in rows}


def list_chats(connection: sqlite3.Connection) -> dict[str, str]:
    """chat_id → 展示名。"""

    try:
        rows = connection.execute("select chat_id, display_name from chats").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row["chat_id"]: row["display_name"] or "" for row in rows}
