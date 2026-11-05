"""Chroma 清理访问层：保守删除策略（阶段 5 批准版，不重建、不重新 Embedding）。

chunk 处置三分类（判定依据 = 解析 metadata.msg_ids → 归一化库时间戳，逐条精确判定，
不信 metadata.date 首条消息日期——chunk 可能跨午夜）：
- delete：chunk 全部消息都属于候选删除日（且不含保护消息）→ 可删文档；
- keep(protected)：含保护日期消息 → 一律保留；
- keep(mixed)：消息跨多个日期（部分需保留）→ 一律保留（本阶段不做部分重建）；
- keep(unresolved)：存在无法解析的 message_id → 一律保留。

注：保守策略下，SQLite 消息删除后，保留的混合 chunk 仍可能检索到已删消息文本——
由候选预览与执行结果向用户明示。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import chromadb

from .db_access import fetch_ts_map
from .protection import date_of_ts

CHUNK_KIND_DELETE = "delete"
KEEP_REASON_PROTECTED = "protected"
KEEP_REASON_MIXED = "mixed"
KEEP_REASON_UNRESOLVED = "unresolved"


@dataclass
class ChunkDisposition:
    chunk_id: str
    action: str  # delete / keep
    reason: str = ""  # protected / mixed / unresolved
    msg_count: int = 0
    dates: set = field(default_factory=set)


def chroma_client(path: Path):
    return chromadb.PersistentClient(path=str(path))


def load_chunk_dispositions(
    client,
    *,
    chat_id: str,
    msg_date: str,
    day_start: int,
    day_end: int,
    normalized_connection: sqlite3.Connection,
    protected: list[str],
) -> list[ChunkDisposition]:
    """对某 (chat, date) 候选组，判定其覆盖范围内所有 chunk 的处置。

    粗筛用 start/end_ts 区间重叠取回候选文档，再逐文档解析 msg_ids 精确判定。
    """

    try:
        collection = client.get_collection("chat_chunks")
    except Exception:
        return []  # 无向量库/空环境：无 chunk 可处置（只读安全）
    result = collection.get(
        where={
            "$and": [
                {"chat_id": {"$eq": chat_id}},
                {"start_ts": {"$lte": day_end - 1}},
                {"end_ts": {"$gte": day_start}},
            ]
        },
        include=["metadatas"],
    )
    dispositions: list[ChunkDisposition] = []
    for chunk_id, meta in zip(result["ids"], result["metadatas"]):
        msg_ids = [m for m in str(meta.get("msg_ids", "")).split(",") if m]
        ts_map = fetch_ts_map(normalized_connection, msg_ids)
        missing = [m for m in msg_ids if m not in ts_map]
        dates = {date_of_ts(ts) for ts in ts_map.values()}
        involved_protected = any(d in protected for d in dates)

        if missing:
            dispositions.append(
                ChunkDisposition(chunk_id, "keep", KEEP_REASON_UNRESOLVED, len(msg_ids), dates)
            )
        elif involved_protected:
            dispositions.append(
                ChunkDisposition(chunk_id, "keep", KEEP_REASON_PROTECTED, len(msg_ids), dates)
            )
        elif dates == {msg_date}:
            dispositions.append(ChunkDisposition(chunk_id, CHUNK_KIND_DELETE, "", len(msg_ids), dates))
        else:
            dispositions.append(
                ChunkDisposition(chunk_id, "keep", KEEP_REASON_MIXED, len(msg_ids), dates)
            )
    return dispositions


def delete_chunks(client, chunk_ids: list[str]) -> None:
    """按文档 ID 删除（Chroma 对不存在 ID 幂等）。"""

    if not chunk_ids:
        return
    client.get_collection("chat_chunks").delete(ids=list(chunk_ids))


def count_chat_chunks(client, chat_id: str) -> int:
    result = client.get_collection("chat_chunks").get(where={"chat_id": {"$eq": chat_id}}, include=[])
    return len(result["ids"])


def update_rag_state(client, *, chat_id: str, total_msgs: int) -> bool:
    """清理后维护 rag_state：total_msgs 用归一化库实际剩余数（权威来源），
    chunk_count 用 Chroma 实际文档数——不用算术推导，避免与 incremental_index
    的"总数减少才全量重建"判定失配。"""

    try:
        state = client.get_collection("rag_state")
    except Exception:
        return False
    existing = state.get(ids=[chat_id], include=["metadatas"])
    if not existing["ids"]:
        return False
    meta = dict(existing["metadatas"][0])
    meta["total_msgs"] = int(total_msgs)
    meta["chunk_count"] = count_chat_chunks(client, chat_id)
    from datetime import datetime

    meta["indexed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state.update(ids=[chat_id], metadatas=[meta])  # 仅更新元数据，不需文档
    return True
