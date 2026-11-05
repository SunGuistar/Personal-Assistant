"""阶段 5 清理测试公共夹具：临时三库 + 临时 Chroma（真实数据零接触）。

构造与真实库一致的 Schema：
- 快照库 chats/messages（chat_id, message_id, create_time, message_json）
- 归一化库 chats/messages（message_id, chat_id, timestamp, time, sender, text, msg_type, render_type）
- Chroma chat_chunks（真实 chunk_messages 切分 + 手工构造的混合/未知 chunk）

时间戳一律显式按 Asia/Shanghai 构造，避免机器时区漂移。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import chromadb
from chromadb.api.types import EmbeddingFunction

SH = timezone(timedelta(hours=8))
CHAT = "10086@chatroom"
CHAT_NAME = "测试群"
PROTECTED_DATE = "2026-10-27"
OLD_DATE = "2026-10-15"  # 可清理（早于今天-7天，配合 today=2026-11-05）
RECENT_DATE = "2026-11-01"  # 不足 7 天，不候选
EDGE_DATE = "2026-11-02"  # 近日期：测试用 today 下不足 7 天，不候选


def ts_of(date_str: str, hour: int = 10, minute: int = 0, second: int = 0) -> int:
    """Asia/Shanghai 本地时间 → epoch 秒。"""

    day = datetime.fromisoformat(date_str)
    return int(datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=SH).timestamp())


def make_messages(chat: str, date_str: str, count: int, *, start_index: int = 0, base_hour: int = 10) -> list[dict]:
    """生成归一化行（60 秒间隔，避免触发间隙切分）。"""

    rows = []
    for i in range(count):
        ts = ts_of(date_str, base_hour) + i * 60
        rows.append(
            {
                "message_id": f"{chat}:msg-{date_str}-{start_index + i}",
                "chat_id": chat,
                "timestamp": ts,
                "time": datetime.fromtimestamp(ts, SH).strftime("%m-%d %H:%M"),
                "sender": f"用户{i % 3}",
                "text": f"{date_str} 的第 {start_index + i} 条消息正文",
                "msg_type": "文本",
                "render_type": "text",
            }
        )
    return rows


class FakeEmbedding(EmbeddingFunction):
    """确定性向量 + 调用计数（增量索引回归断言用）。"""

    def __init__(self) -> None:
        self.documents = 0

    def name(self) -> str:
        return "fake-embedding"

    def __call__(self, input):
        self.documents += len(input)
        return [[0.01] * 64 for _ in input]


@dataclass
class CleanupEnv:
    snapshot: Path
    normalized: Path
    chroma: Path
    ef: FakeEmbedding

    @property
    def paths(self):
        from app.cleanup.service import CleanupPaths

        return CleanupPaths(snapshot=self.snapshot, normalized=self.normalized, chroma=self.chroma)


def _create_snapshot(path: Path, chat: str, messages: list[dict]) -> None:
    from app.wechat_agent.data_api.message_store import MessageStore

    with MessageStore(path):
        pass  # __init__ 已建 schema
    con = sqlite3.connect(path)
    con.execute(
        "insert into chats (chat_id, display_name, saved_at) values (?, ?, ?)",
        (chat, CHAT_NAME, "2026-11-01 00:00:00"),
    )
    for row in messages:
        con.execute(
            "insert into messages (chat_id, message_id, create_time, message_json) values (?, ?, ?, ?)",
            (chat, row["message_id"], row["timestamp"], json.dumps({"id": row["message_id"], "createTime": row["timestamp"]})),
        )
    con.commit()
    con.close()


def _create_normalized(path: Path, chat: str, messages: list[dict]) -> None:
    from app.wechat_agent.data_api.normalize_snapshot import _ensure_schema

    con = sqlite3.connect(path)
    _ensure_schema(con)
    con.execute(
        "insert into chats (chat_id, display_name, normalized_at) values (?, ?, ?)",
        (chat, CHAT_NAME, "2026-11-01 00:00:00"),
    )
    for row in messages:
        con.execute(
            "insert into messages (message_id, chat_id, timestamp, time, sender, text, msg_type, render_type)"
            " values (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["message_id"], row["chat_id"], row["timestamp"], row["time"],
                row["sender"], row["text"], row["msg_type"], row["render_type"],
            ),
        )
    con.commit()
    con.close()


def build_env(tmp_path: Path, messages: list[dict], chat: str = CHAT) -> CleanupEnv:
    """按消息集构造临时三库（Chroma 由调用方按需填充）。"""

    snapshot = tmp_path / "chat_snapshot.sqlite3"
    normalized = tmp_path / "chat_snapshot_normalized.sqlite3"
    _create_snapshot(snapshot, chat, messages)
    _create_normalized(normalized, chat, messages)
    return CleanupEnv(snapshot=snapshot, normalized=normalized, chroma=tmp_path / "chroma_db", ef=FakeEmbedding())


def chroma_client_with(env: CleanupEnv):
    client = chromadb.PersistentClient(path=str(env.chroma))
    return client


def upsert_chunk_docs(client, chunks: list, ef: FakeEmbedding | None = None) -> None:
    """真实 metadata 结构写入（与 rag_store._upsert_chunks 一致）。

    ef：必须传 FakeEmbedding，否则 chromadb 默认 ONNX embedding 会联网下载（测试挂起）。
    """

    collection = client.get_or_create_collection("chat_chunks", embedding_function=ef)
    if not chunks:
        return
    collection.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[
            {
                "chat_id": c.chat_id,
                "date": c.date,
                "start_ts": c.start_ts,
                "end_ts": c.end_ts,
                "msg_ids": ",".join(str(i) for i in c.msg_ids),
                "senders": ",".join(c.senders),
                "content_hash": c.content_hash,
            }
            for c in chunks
        ],
    )


def build_real_chunks(messages: list[dict], chat: str = CHAT) -> list:
    """用真实 chunk_messages 切分（跨日期消息放同一列表也能反映混合行为）。"""

    from app.wechat_agent.normal_tools.chunking import chunk_messages

    return chunk_messages(messages)


def make_manual_chunk(chat: str, messages: list[dict], date: str):
    """手工构造 chunk（混合日期/特殊场景测试用）。"""

    from app.wechat_agent.normal_tools.chunking import Chunk
    import hashlib

    text = "\n".join(f"[{m['time']}] {m['sender']}: {m['text']} (#{m['message_id']})" for m in messages)
    return Chunk(
        msg_ids=[m["message_id"] for m in messages],
        chat_id=chat,
        date=date,
        senders=sorted({m["sender"] for m in messages}),
        start_ts=min(m["timestamp"] for m in messages),
        end_ts=max(m["timestamp"] for m in messages),
        text=text,
        content_hash=hashlib.sha1(text.encode("utf-8")).hexdigest()[:16],
    )


def set_rag_state(client, chat: str, *, total_msgs: int, chunk_count: int, last_ts: int, last_start_ts: int, ef: "FakeEmbedding | None" = None) -> None:
    state = client.get_or_create_collection("rag_state", embedding_function=ef)
    state.upsert(
        ids=[chat],
        documents=[""],
        metadatas=[{
            "chat_id": chat,
            "last_msg_id": "manual",
            "last_timestamp": last_ts,
            "last_chunk_start_ts": last_start_ts,
            "chunk_count": chunk_count,
            "total_msgs": total_msgs,
            "indexed_at": "2026-11-01 00:00:00",
        }],
    )


def normalized_count(path: Path, chat: str | None = None) -> int:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if chat:
            return con.execute("select count(*) from messages where chat_id = ?", (chat,)).fetchone()[0]
        return con.execute("select count(*) from messages").fetchone()[0]
    finally:
        con.close()


def snapshot_count(path: Path, chat: str) -> int:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("select count(*) from messages where chat_id = ?", (chat,)).fetchone()[0]
    finally:
        con.close()
