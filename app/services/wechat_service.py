"""微信同步编排（阶段 3.6，按用户调整一设计）。

可靠性模型：
- **重叠窗口**：API 仅支持 offset 分页 + desc 排序 + 客户端时间过滤，
  故每次同步拉取 [游标时间 - 24h, 现在] 的全部分页，靠稳定 message_id
  主键幂等 upsert，容忍迟到的同秒消息与重试。
- **游标后置**：原始快照 → 归一化 两步都提交后，才推进 sync_cursors
  （hub.db）；任何一步失败游标不动，重试安全。
- **指纹去重**：归一化写入前清理同 (时间,发言人,类型,内容) 旧行（重复
  导出的新 id 不产生重复消息）。
- **对账补录**：同步完成后按日比对原始/归一化计数，差异日自动重建该日。
- 向量索引走 rag_store.incremental_index（rag_state 游标，chunk_id 确定性），
  失败可重试且不破坏旧索引。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SyncCursor
from app.wechat_agent.data_api.message_store import MessageStore
from app.wechat_agent.data_api.normalize_snapshot import normalize_chat
from app.wechat_agent.normal_tools import rag_store

logger = logging.getLogger(__name__)

OVERLAP_SECONDS = 24 * 3600  # 重叠窗口（个人群聊足够，可调）

RAW_DB_PATH = Path(__file__).resolve().parent.parent.parent / "GetWechatInfo" / "DataInfo" / "chat_snapshot.sqlite3"
NORMALIZED_DB_PATH = RAW_DB_PATH.with_name("chat_snapshot_normalized.sqlite3")


class SourceClient(Protocol):
    """同步依赖的客户端最小接口（适配器/测试替身均实现）。"""

    def iter_messages(
        self, username: str, *, start_ts: int, end_ts: int, batch_size: int = 500
    ) -> Iterable[dict]: ...


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _row_id(chat_id: str, row: dict) -> tuple[int, str]:
    """稳定排序键：(timestamp, message_id)——游标推进与"新增"判定都靠它。"""

    return (int(row.get("createTime", 0) or 0), str(row.get("id", "")))


def _get_cursor(session: Session, chat_id: str) -> SyncCursor | None:
    return session.get(SyncCursor, chat_id)


def _advance_cursor(session: Session, chat_id: str, rows: list[dict]) -> None:
    """游标推进到本批最大 (timestamp, message_id)（调用方已先提交消息）。"""

    if not rows:
        return
    last_ts, last_id = max(_row_id("", row) for row in rows)
    cursor = _get_cursor(session, chat_id)
    if cursor is None:
        cursor = SyncCursor(scope=chat_id, last_timestamp=0, last_msg_id="")
        session.add(cursor)
    current = (cursor.last_timestamp or 0, cursor.last_msg_id or "")
    if (last_ts, last_id) > current:
        cursor.last_timestamp = last_ts
        cursor.last_msg_id = last_id
    session.commit()


def count_new_rows(rows: list[dict], cursor: SyncCursor | None) -> int:
    """相对游标严格新增的行数（重叠重传的行不算新增）。"""

    if cursor is None:
        return len(rows)
    boundary = (cursor.last_timestamp, cursor.last_msg_id)
    return sum(1 for row in rows if _row_id("", row) > boundary)


def sync_chat(
    session: Session,
    client: SourceClient,
    chat_id: str,
    display_name: str,
    *,
    now_ts: int | None = None,
    overlap_seconds: int = OVERLAP_SECONDS,
) -> dict[str, int]:
    """单群增量同步（重叠窗口 + 幂等 + 游标后置）。"""

    end_ts = now_ts or int(time.time())
    cursor = _get_cursor(session, chat_id)
    since_ts = max(0, cursor.last_timestamp - overlap_seconds) if cursor else 0

    rows = list(
        client.iter_messages(chat_id, start_ts=since_ts, end_ts=end_ts, batch_size=500)
    )
    new_count = count_new_rows(rows, cursor)

    # 1) 原始快照（主键幂等）
    with MessageStore(RAW_DB_PATH) as store:
        store.upsert_rows(chat_id, rows)
        store.record_chat(chat_id, display_name)

    # 2) 归一化（区间 upsert + 指纹去重，独立提交）
    raw = _connect(RAW_DB_PATH, readonly=True)
    normalized = _connect(NORMALIZED_DB_PATH)
    try:
        normalize_chat(raw, normalized, chat_id, display_name, start_ts=since_ts, end_ts=end_ts)
    finally:
        raw.close()
        normalized.close()

    # 3) 游标推进（前两步已成功）
    _advance_cursor(session, chat_id, rows)
    return {"fetched": len(rows), "new": new_count}


def reconcile_chat(session: Session, chat_id: str, display_name: str) -> list[str]:
    """按日对账：原始 vs 归一化计数差异日 → 重建该日（replace 语义，幂等）。

    返回被补录的日期列表。
    """

    raw = _connect(RAW_DB_PATH, readonly=True)
    normalized = _connect(NORMALIZED_DB_PATH)
    try:
        raw_days = {
            day: count
            for day, count in raw.execute(
                """SELECT date(create_time, 'unixepoch', 'localtime') AS day, count(*)
                   FROM messages WHERE chat_id = ? GROUP BY day""",
                (chat_id,),
            )
        }
        norm_days = {
            day: count
            for day, count in normalized.execute(
                """SELECT date(timestamp, 'unixepoch', 'localtime') AS day, count(*)
                   FROM messages WHERE chat_id = ? GROUP BY day""",
                (chat_id,),
            )
        }
        mismatched = [
            day for day in sorted(set(raw_days) | set(norm_days))
            if raw_days.get(day, 0) != norm_days.get(day, 0)
        ]
        for day in mismatched:
            day_start = int(datetime.strptime(day, "%Y-%m-%d").timestamp())
            day_end = day_start + 86399
            normalize_chat(
                raw, normalized, chat_id, display_name,
                start_ts=day_start, end_ts=day_end, replace=True,
            )
            logger.info("对账补录 %s %s", chat_id, day)
        return mismatched
    finally:
        raw.close()
        normalized.close()


def resync_range(
    session: Session,
    client: SourceClient,
    chat_id: str,
    display_name: str,
    *,
    start: str,
    end: str,
) -> int:
    """指定日期范围重新同步（历史补录）：重新拉取 API → 原始库幂等覆盖
    → 归一化 replace。用于重叠窗口之外的历史修正。
    """

    start_ts = int(datetime.strptime(start, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp())
    rows = list(client.iter_messages(chat_id, start_ts=start_ts, end_ts=end_ts, batch_size=500))
    with MessageStore(RAW_DB_PATH) as store:
        store.upsert_rows(chat_id, rows)
        store.record_chat(chat_id, display_name)
    raw = _connect(RAW_DB_PATH, readonly=True)
    normalized = _connect(NORMALIZED_DB_PATH)
    try:
        count = normalize_chat(
            raw, normalized, chat_id, display_name,
            start_ts=start_ts, end_ts=end_ts, replace=True,
        )
    finally:
        raw.close()
        normalized.close()
    return count


def run_sync_job(
    session: Session,
    client: SourceClient,
    *,
    chat_id: str | None = None,
    display_name: str = "",
    start: str | None = None,
    end: str | None = None,
    progress_cb: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """同步任务体（任务执行器调用）。指定 start/end 时只做范围补录。"""

    def report(value: int) -> None:
        if progress_cb:
            progress_cb(value)

    targets = [(chat_id, display_name)] if chat_id else []
    if not chat_id and not start:
        # 全群同步：以本地归一化库中的群为目标（先同步已入库的群）
        normalized = _connect(NORMALIZED_DB_PATH, readonly=True)
        try:
            targets = [
                (str(row[0]), str(row[1]))
                for row in normalized.execute("SELECT chat_id, display_name FROM chats")
            ]
        finally:
            normalized.close()
        if not targets:
            raise RuntimeError("本地聊天库为空，请先通过指定群同步拉取数据。")

    results: dict[str, Any] = {"chats": {}, "reconciled": {}, "index": {}}
    total = len(targets)
    for index, (cid, name) in enumerate(targets):
        if start and end:
            results["chats"][cid] = {"resynced": resync_range(session, client, cid, name, start=start, end=end)}
        else:
            results["chats"][cid] = sync_chat(session, client, cid, name)
        report(int((index + 1) / (total + 1) * 90))
    # 对账 + 增量索引（进度 90→100）
    for index, (cid, name) in enumerate(targets):
        results["reconciled"][cid] = reconcile_chat(session, cid, name)
        report(90 + int((index + 1) / (total + 1) * 8))
    results["index"] = rag_store.incremental_index()
    report(100)
    return results


def data_range() -> list[dict[str, Any]]:
    """本地聊天库各群的数据时间范围（只读）。"""

    normalized = _connect(NORMALIZED_DB_PATH, readonly=True)
    try:
        rows = normalized.execute(
            """SELECT c.chat_id, c.display_name,
                      count(m.message_id),
                      min(m.timestamp), max(m.timestamp)
               FROM chats c LEFT JOIN messages m ON m.chat_id = c.chat_id
               GROUP BY c.chat_id ORDER BY c.chat_id"""
        ).fetchall()
    finally:
        normalized.close()
    result = []
    for chat_id, name, count, min_ts, max_ts in rows:
        result.append(
            {
                "chat_id": chat_id,
                "display_name": name,
                "message_count": int(count or 0),
                "min_date": datetime.fromtimestamp(min_ts).strftime("%Y-%m-%d") if min_ts else None,
                "max_date": datetime.fromtimestamp(max_ts).strftime("%Y-%m-%d") if max_ts else None,
            }
        )
    return result
