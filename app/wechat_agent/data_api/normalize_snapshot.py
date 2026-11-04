"""normalize_snapshot.py：原始快照库 → 归一化库（阶段 3.4 重建）。

缺失多年的历史脚本：逻辑由 structured_message 的归一化规则 + 归一化库
Schema 推导，与历史归一化库逐行对拍验证（见 tests/test_normalize_rebuild.py）。

语义：
- 按群处理；--all 模式对该群"先删后写"（替换语义，幂等）；
  指定 --start/--end 时仅幂等 upsert 该区间的消息。
- 主键 (chat_id, message_id)，重复执行不产生重复行。

用法：
    python -m app.wechat_agent.data_api.normalize_snapshot --all
    python -m app.wechat_agent.data_api.normalize_snapshot --chat <chat_id> --start "2026-11-01" --end "2026-11-02"
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from env_bootstrap import load_hub_env  # noqa: E402

load_hub_env()

from app.wechat_agent.structured.structured_message import from_raw_rows  # noqa: E402

logger = logging.getLogger(__name__)

RAW_DB_PATH = ROOT_DIR / "GetWechatInfo" / "DataInfo" / "chat_snapshot.sqlite3"
NORMALIZED_DB_PATH = ROOT_DIR / "GetWechatInfo" / "DataInfo" / "chat_snapshot_normalized.sqlite3"

NORMALIZED_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS chats (
        chat_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        normalized_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS messages (
        message_id TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        time TEXT NOT NULL,
        sender TEXT NOT NULL,
        text TEXT NOT NULL,
        msg_type TEXT NOT NULL,
        render_type TEXT NOT NULL,
        PRIMARY KEY(chat_id, message_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_id, timestamp)",
)


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    for statement in NORMALIZED_SCHEMA:
        connection.execute(statement)
    connection.commit()


def _parse_boundary(text: str | None, *, is_end: bool) -> int | None:
    if not text:
        return None
    parsed = datetime.strptime(text.strip(), "%Y-%m-%d")
    if is_end:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return int(parsed.timestamp())


def load_raw_rows(raw: sqlite3.Connection, chat_id: str, start_ts: int | None, end_ts: int | None) -> list[dict]:
    clauses, params = ["chat_id = ?"], [chat_id]
    if start_ts is not None:
        clauses.append("create_time >= ?")
        params.append(start_ts)
    if end_ts is not None:
        clauses.append("create_time <= ?")
        params.append(end_ts)
    rows = raw.execute(
        f"SELECT message_json FROM messages WHERE {' AND '.join(clauses)} ORDER BY create_time",
        params,
    ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _delete_fingerprint_duplicates(
    normalized: sqlite3.Connection, chat_id: str, messages
) -> None:
    """清理同指纹旧行：同一秒同发言人同内容的历史行（重复导出会产生
    新 message_id，历史库全量重建时靠 from_raw_rows 去重，增量模式
    在这里兜底，保证归一化库指纹唯一）。
    """

    for message in messages:
        normalized.execute(
            """DELETE FROM messages WHERE chat_id = ? AND timestamp = ? AND sender = ?
               AND msg_type = ? AND text = ? AND message_id <> ?""",
            (chat_id, message.timestamp, message.sender, message.msg_type, message.text, message.id),
        )


def normalize_chat(
    raw: sqlite3.Connection,
    normalized: sqlite3.Connection,
    chat_id: str,
    display_name: str,
    *,
    start_ts: int | None = None,
    end_ts: int | None = None,
    replace: bool = False,
) -> int:
    """归一化单个群并写入；replace=True 时先清空该群消息（全量语义）。"""

    raw_rows = load_raw_rows(raw, chat_id, start_ts, end_ts)
    messages = from_raw_rows(chat_id, raw_rows)
    with normalized:
        if replace:
            normalized.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        _delete_fingerprint_duplicates(normalized, chat_id, messages)
        normalized.executemany(
            """INSERT OR REPLACE INTO messages
               (message_id, chat_id, timestamp, time, sender, text, msg_type, render_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    message.id,
                    message.chat_id,
                    message.timestamp,
                    message.time,
                    message.sender,
                    message.text,
                    message.msg_type,
                    message.render_type,
                )
                for message in messages
            ],
        )
        normalized.execute(
            """INSERT INTO chats(chat_id, display_name, normalized_at) VALUES(?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                   display_name = excluded.display_name,
                   normalized_at = excluded.normalized_at""",
            (chat_id, display_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
    logger.info("归一化 %s (%s): %d 条", display_name, chat_id, len(messages))
    return len(messages)


def run_normalize(
    *,
    raw_path: Path = RAW_DB_PATH,
    normalized_path: Path = NORMALIZED_DB_PATH,
    chat_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    all_chats: bool = False,
) -> dict[str, int]:
    """入口：全量（--all）或按群/按区间归一化。返回 {chat_id: 条数}。"""

    if not all_chats and not chat_id:
        raise ValueError("请指定 --all 或 --chat。")
    raw = _connect(raw_path, readonly=True)
    normalized = _connect(normalized_path)
    try:
        _ensure_schema(normalized)
        chats = raw.execute("SELECT chat_id, display_name FROM chats").fetchall()
        if chat_id:
            chats = [row for row in chats if row[0] == chat_id]
            if not chats:
                raise ValueError(f"原始快照库中找不到群: {chat_id}")
        start_ts = _parse_boundary(start, is_end=False) if (start or end) else None
        end_ts = _parse_boundary(end, is_end=True) if (start or end) else None
        stats: dict[str, int] = {}
        for cid, name in chats:
            stats[cid] = normalize_chat(
                raw, normalized, cid, name,
                start_ts=start_ts, end_ts=end_ts,
                replace=all_chats,
            )
        return stats
    finally:
        raw.close()
        normalized.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", default=str(RAW_DB_PATH), help="原始快照库路径")
    parser.add_argument("--db", default=str(NORMALIZED_DB_PATH), help="归一化库路径")
    parser.add_argument("--chat", default="", help="只处理指定 chat_id")
    parser.add_argument("--start", default="", help="起始日期 YYYY-MM-DD（与 --end 成对）")
    parser.add_argument("--end", default="", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--all", action="store_true", help="全量重建（替换语义，幂等）")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    stats = run_normalize(
        raw_path=Path(args.raw),
        normalized_path=Path(args.db),
        chat_id=args.chat or None,
        start=args.start or None,
        end=args.end or None,
        all_chats=args.all,
    )
    for cid, count in stats.items():
        print(f"{cid}: {count} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
