"""聊天记录分块（Chunking）：把归一化库的消息流切成适合语义检索的 Chunk。

组合式切分策略：
- 时间间隔：相邻消息间隔超过 GAP_SECONDS（5 分钟）时切分——切断不连续的对话；
- 消息数量：每 Chunk 最多 MAX_MESSAGES_PER_CHUNK 条；
- 文本长度：Chunk 正文累计超过 MAX_CHUNK_CHARS 字符时切分；
  单条消息本身超限时不再触发切分（拆消息正文会破坏原文回溯），
  该消息并入当前 Chunk，其所在 Chunk 允许超出上限（软约束）;
- 重叠机制：因数量/长度切分的相邻 Chunk 共享末尾 OVERLAP_MESSAGES 条消息，
  降低上下文截断造成的语义损失；时间间隔切分不重叠（跨间隙的重叠是噪声）。

每个 Chunk 保留：消息 ID 列表、群聊 ID、日期、发言人集合、起止时间戳、
正文（沿用 "[MM-DD HH:MM] 发送者: 正文 (#消息ID)" 格式）与内容哈希。

只读消费上游数据，不修改任何 SQLite 内容。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

GAP_SECONDS = 300          # 时间间隔切分阈值：5 分钟
MAX_MESSAGES_PER_CHUNK = 15
MAX_CHUNK_CHARS = 800      # 单 Chunk 正文字符上限（约 800 token 量级）
OVERLAP_MESSAGES = 2       # 数量/长度切分时的重叠消息数

# 消息行的内部表示：与归一化库 messages 表列对应（chunk_messages 的输入）
Message = dict


@dataclass
class Chunk:
    """一个检索单元：若干条连续消息的聚合。"""

    msg_ids: list[str]        # 原始消息 ID（归一化库主键，字符串，如 "message_8:Msg_...:240007"）
    chat_id: str
    date: str               # 首条消息的日期 YYYY-MM-DD
    senders: list[str]      # 去重后的发言人列表（保持出现顺序）
    start_ts: int           # 首条消息时间戳
    end_ts: int             # 末条消息时间戳
    text: str               # 正文（含消息 ID，可直接展示给 LLM/嵌入模型）
    content_hash: str       # 正文哈希：识别"消息被修改"的情况

    @property
    def chunk_id(self) -> str:
        """确定性 ID：同一批消息 IDs 永远得到同一个 chunk_id。

        增量索引据此防重复写入；消息内容变了但边界没变时 ID 不变，
        由 content_hash 的变化识别并触发更新（upsert 语义）。
        """

        raw = f"{self.chat_id}|{','.join(str(i) for i in self.msg_ids)}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _line(m: Message) -> str:
    return f"[{m['time']}] {m['sender']}: {m['text']} (#{m['message_id']})"


def _make_chunk(messages: list[Message]) -> Chunk:
    first, last = messages[0], messages[-1]
    senders: list[str] = []
    for m in messages:
        if m["sender"] not in senders:
            senders.append(m["sender"])
    text = "\n".join(_line(m) for m in messages)
    return Chunk(
        msg_ids=[m["message_id"] for m in messages],
        chat_id=first["chat_id"],
        date=datetime.fromtimestamp(first["timestamp"]).strftime("%Y-%m-%d"),
        senders=senders,
        start_ts=first["timestamp"],
        end_ts=last["timestamp"],
        text=text,
        content_hash=hashlib.sha1(text.encode("utf-8")).hexdigest()[:16],
    )


def chunk_messages(messages: list[Message]) -> list[Chunk]:
    """把某个群的全部消息（按 timestamp 排序后）切成 Chunk。

    保证：输入的每条消息至少出现在一个 Chunk 中，消息正文不被修改，
    且算法必然终止（每个 Chunk 至少含一条新消息）。

    重叠采用惰性种子：上一 Chunk 的末尾消息只在能与本条新消息
    合放（且不跨时间间隙）时才并入新 Chunk，避免"种子放不下导致
    空转重复"。超长消息所在 Chunk 允许超出字符上限（软约束）。
    """

    msgs = sorted(messages, key=lambda m: m["timestamp"])
    chunks: list[Chunk] = []
    prev_tail: list[Message] = []  # 上一个 Chunk 的末尾消息，作为重叠种子
    i = 0
    n = len(msgs)

    while i < n:
        buf: list[Message] = []
        buf_chars = 0
        if prev_tail:
            first = msgs[i]
            seed_chars = sum(len(t["text"]) for t in prev_tail)
            # 种子仅在与新消息时间连续、合放得下时才生效
            if (
                first["timestamp"] - prev_tail[-1]["timestamp"] <= GAP_SECONDS
                and seed_chars + len(first["text"]) <= MAX_CHUNK_CHARS
            ):
                buf = list(prev_tail)
                buf_chars = seed_chars
            prev_tail = []

        gap_break = False
        while i < n:
            m = msgs[i]
            if buf:
                if m["timestamp"] - buf[-1]["timestamp"] > GAP_SECONDS:
                    gap_break = True  # 时间不连续：切分，且不重叠
                    break
                if len(buf) >= MAX_MESSAGES_PER_CHUNK:
                    break
                # 超长消息（单条即超上限）不触发切分，直接并入当前 Chunk
                if (
                    buf_chars + len(m["text"]) > MAX_CHUNK_CHARS
                    and len(m["text"]) <= MAX_CHUNK_CHARS
                ):
                    break
            buf.append(m)
            buf_chars += len(m["text"])
            i += 1

        chunks.append(_make_chunk(buf))
        # 数量/长度切分时，下一 Chunk 继承末尾几条消息做重叠
        if not gap_break and i < n:
            prev_tail = buf[-OVERLAP_MESSAGES:]

    return chunks
