"""微信聊天记录快照库：一次从 WeChatDataAnalysis 导出，之后离线复用。

用法：
    # 一次性导出（在线，需要 WeChatDataAnalysis 运行中）
    python message_store.py export --chat <群名或chat_id> --date 2026-10-27

    # 离线读取（验证或交给下游分析）
    python message_store.py load --chat <chat_id> --date 2026-10-27

    # 查看库里已保存的群
    python message_store.py list

存储策略：保留 API 原始行 JSON，不做字段裁剪，后续任何归一化逻辑都可以重放。
手动刷新 = 再跑一次 export（主键幂等覆盖）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # 支持 `python message_store.py` 和包内导入两种方式
    from .wechat_data_api import WeChatDataAPIClient, WeChatDataAPIError
except ImportError:  # pragma: no cover - 直接作为脚本运行时触发
    from wechat_data_api import WeChatDataAPIClient, WeChatDataAPIError


DATABASE_SCHEMA_VERSION = 1
DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "GetWechatInfo" / "DataInfo" / "chat_snapshot.sqlite3"
)

BASE_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS chats (
        chat_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        saved_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS messages (
        chat_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        create_time INTEGER NOT NULL,
        message_json TEXT NOT NULL,
        PRIMARY KEY(chat_id, message_id)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_id, create_time)""",
)


def _parse_time_range(date: str, start: str, end: str) -> tuple[int, int]:
    """解析单日或起止时间，返回 [start_ts, end_ts] 闭区间。"""

    if date:
        day = datetime.strptime(date.strip(), "%Y-%m-%d")
        return int(day.replace(hour=0, minute=0, second=0).timestamp()), int(
            day.replace(hour=23, minute=59, second=59).timestamp()
        )
    if not start or not end:
        raise ValueError("请传 --date YYYY-MM-DD，或同时传 --start 与 --end。")
    start_ts = _parse_boundary(start.strip(), is_end=False)
    end_ts = _parse_boundary(end.strip(), is_end=True)
    return start_ts, end_ts


def _parse_boundary(text: str, *, is_end: bool) -> int:
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        if pattern == "%Y-%m-%d" and is_end:
            parsed = parsed.replace(hour=23, minute=59, second=59)
        return int(parsed.timestamp())
    raise ValueError(f"无法解析时间: {text}")


def _row_message_id(chat_id: str, row: dict[str, Any]) -> str:
    raw_id = str(row.get("id") or "").strip()
    if raw_id:
        return raw_id
    seed = "|".join(
        [
            chat_id,
            str(row.get("createTime", "") or ""),
            str(row.get("senderUsername", "") or ""),
            str(row.get("content", "") or ""),
        ]
    )
    return "m_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


class MessageStore:
    """按 chat_id + message_id 主键存取 API 原始消息行的 SQLite 快照库。"""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        try:
            self._ensure_schema()
        except Exception:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "MessageStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @classmethod
    def _migrate_v0_to_v1(cls, connection: sqlite3.Connection) -> None:
        for statement in BASE_SCHEMA_STATEMENTS:
            connection.execute(statement)

    def _ensure_schema(self) -> None:
        current_version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version > DATABASE_SCHEMA_VERSION:
            raise RuntimeError(
                f"消息库版本 {current_version} 高于当前程序支持的 {DATABASE_SCHEMA_VERSION}。"
            )
        migrations = {1: self._migrate_v0_to_v1}
        for target_version in range(current_version + 1, DATABASE_SCHEMA_VERSION + 1):
            migration = migrations.get(target_version)
            if migration is None:
                raise RuntimeError(f"缺少消息库 migration: v{target_version - 1} -> v{target_version}")
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                migration(self.connection)
                self.connection.execute(f"PRAGMA user_version = {target_version}")
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def record_chat(self, chat_id: str, display_name: str) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO chats(chat_id, display_name, saved_at) VALUES(?,?,?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                       display_name = excluded.display_name,
                       saved_at = excluded.saved_at""",
                (chat_id, display_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )

    def upsert_rows(self, chat_id: str, rows: list[dict[str, Any]]) -> int:
        """按主键幂等写入消息行，返回写入条数。"""

        if not rows:
            return 0
        payload = [
            (
                chat_id,
                _row_message_id(chat_id, row),
                int(row.get("createTime", 0) or 0),
                json.dumps(row, ensure_ascii=False, sort_keys=True),
            )
            for row in rows
        ]
        with self.connection:
            self.connection.executemany(
                """INSERT OR REPLACE INTO messages(chat_id, message_id, create_time, message_json)
                   VALUES(?,?,?,?)""",
                payload,
            )
        return len(payload)

    def load_rows(
        self,
        chat_id: str,
        start_ts: int,
        end_ts: int,
    ) -> list[dict[str, Any]]:
        """按 chat_id + 时间范围读取原始消息行，按时间升序返回。"""

        rows = self.connection.execute(
            """SELECT message_json FROM messages
               WHERE chat_id = ? AND create_time >= ? AND create_time <= ?
               ORDER BY create_time, message_id""",
            (chat_id, int(start_ts), int(end_ts)),
        ).fetchall()
        return [json.loads(row["message_json"]) for row in rows]

    def count_rows(self, chat_id: str, start_ts: int, end_ts: int) -> int:
        row = self.connection.execute(
            "SELECT count(*) FROM messages WHERE chat_id = ? AND create_time >= ? AND create_time <= ?",
            (chat_id, int(start_ts), int(end_ts)),
        ).fetchone()
        return int(row[0])

    def resolve_chat(self, chat_ref: str) -> tuple[str, str]:
        """按 chat_id 精确或群名唯一匹配；歧义时 fail-fast。"""

        ref = str(chat_ref or "").strip()
        if not ref:
            raise ValueError("必须通过 --chat 传入群聊名称或 chat_id。")
        row = self.connection.execute(
            "SELECT chat_id, display_name FROM chats WHERE chat_id = ?", (ref,)
        ).fetchone()
        if row:
            return str(row["chat_id"]), str(row["display_name"])
        rows = self.connection.execute(
            "SELECT chat_id, display_name FROM chats WHERE display_name = ?", (ref,)
        ).fetchall()
        if len(rows) == 1:
            return str(rows[0]["chat_id"]), str(rows[0]["display_name"])
        if len(rows) > 1:
            raise ValueError(f"快照库中存在多个同名群聊 {ref!r}，请改用 chat_id。")
        raise ValueError(f"快照库中找不到群聊 {ref!r}，请先 export。")

    def list_chats(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT c.chat_id, c.display_name, c.saved_at,
                      (SELECT count(*) FROM messages m WHERE m.chat_id = c.chat_id) AS message_count
               FROM chats c ORDER BY c.saved_at DESC"""
        ).fetchall()
        return [dict(row) for row in rows]


def cmd_export(args: argparse.Namespace) -> int:
    start_ts, end_ts = _parse_time_range(args.date, args.start, args.end)
    client = WeChatDataAPIClient(
        args.api_url,
        account=args.account,
        source=args.source,
        timeout=args.timeout,
    )
    chat = client.resolve_chat(args.chat)
    rows = list(
        client.iter_messages(
            chat.username,
            start_ts=start_ts,
            end_ts=end_ts,
            batch_size=args.batch_size,
        )
    )
    if not rows:
        print(f"指定范围内没有消息（{chat.display_name}）。")
        return 1
    with MessageStore(args.db) as store:
        written = store.upsert_rows(chat.username, rows)
        store.record_chat(chat.username, chat.display_name)
    print(
        f"已保存 {written} 条消息：{chat.display_name} ({chat.username}) → {Path(args.db).expanduser()}"
    )
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    start_ts, end_ts = _parse_time_range(args.date, args.start, args.end)
    with MessageStore(args.db) as store:
        chat_id, display_name = store.resolve_chat(args.chat)
        rows = store.load_rows(chat_id, start_ts, end_ts)
    if not rows:
        print(f"快照库中该范围没有消息（{display_name}）。")
        return 1
    senders = {
        str(row.get("senderDisplayName") or row.get("senderUsername") or "unknown")
        for row in rows
    }
    print(f"群聊: {display_name} ({chat_id})")
    print(f"消息数: {len(rows)}，发言人数: {len(senders)}")
    print(f"时间范围: {_format_ts(rows[0].get('createTime'))} ~ {_format_ts(rows[-1].get('createTime'))}")
    if args.dump:
        for row in rows[: args.limit] if args.limit else rows:
            print(json.dumps(row, ensure_ascii=False))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    with MessageStore(args.db) as store:
        chats = store.list_chats()
    if not chats:
        print("快照库为空。")
        return 0
    for item in chats:
        print(
            f"{item['display_name']} ({item['chat_id']}) "
            f"- {item['message_count']} 条，最近保存 {item['saved_at']}"
        )
    return 0


def _format_ts(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value or 0)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "未知时间"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help=f"SQLite 快照库路径，默认 {DEFAULT_DB_PATH}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="在线读取并保存到快照库（手动刷新=再跑一次）")
    export_parser.add_argument("--chat", required=True, help="群聊名称或 @chatroom ID。")
    export_parser.add_argument("--date", default="", help="单日，格式 YYYY-MM-DD。")
    export_parser.add_argument("--start", default="", help="开始时间，与 --end 成对使用。")
    export_parser.add_argument("--end", default="", help="结束时间，与 --start 成对使用。")
    export_parser.add_argument("--api-url", default="http://127.0.0.1:10392", help="WeChatDataAnalysis 本地 API 地址。")
    export_parser.add_argument("--account", default="", help="可选微信账号标识。")
    export_parser.add_argument("--source", default="", help="可选数据源标识。")
    export_parser.add_argument("--batch-size", type=int, default=500, help="分页大小，默认 500。")
    export_parser.add_argument("--timeout", type=float, default=30.0, help="API 超时秒数。")
    export_parser.set_defaults(handler=cmd_export)

    load_parser = subparsers.add_parser("load", help="离线从快照库读取，不访问 API。")
    load_parser.add_argument("--chat", required=True, help="chat_id 或已保存的群名。")
    load_parser.add_argument("--date", default="", help="单日，格式 YYYY-MM-DD。")
    load_parser.add_argument("--start", default="", help="开始时间，与 --end 成对使用。")
    load_parser.add_argument("--end", default="", help="结束时间，与 --start 成对使用。")
    load_parser.add_argument("--dump", action="store_true", help="打印原始消息 JSON。")
    load_parser.add_argument("--limit", type=int, default=0, help="配合 --dump 最多打印多少条，0 为全部。")
    load_parser.set_defaults(handler=cmd_load)

    list_parser = subparsers.add_parser("list", help="列出快照库中已保存的群。")
    list_parser.set_defaults(handler=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (ValueError, WeChatDataAPIError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
