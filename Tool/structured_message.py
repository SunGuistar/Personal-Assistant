"""轻量消息结构：把 WeChatDataAnalysis 原始消息行转成 LLM 可读的统一格式。

只做最基本的清洗：
- 发送者取 senderDisplayName 并去除 \\x7f 占位字符；
- 正文按消息类型从 content / title / voiceTranscript / url 中提取；
- 时间戳转为本地可读时间。

不做人名兜底、碰撞修复、XML 富文本解析（那些属于报告级清洗，问答场景不需要）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class StructuredMessage:
    """归一化后的单条微信消息。"""

    id: str
    timestamp: int
    time: str  # 本地时间，格式 %m-%d %H:%M
    sender: str
    text: str
    msg_type: str  # 文本 / 图片 / 语音 / 视频 / 表情 / 链接/文件 / 系统
    render_type: str  # 原始 renderType，小写，供需要细分的场景使用
    chat_id: str

    def to_llm_line(self) -> str:
        """转成单行文本，直接拼接进 prompt。"""
        return f"[{self.time}] {self.sender}: {self.text}"


_IGNORED_NAME_CHARS = "\x7f"

# renderType -> (msg_type, 正文提取字段优先级, 空内容占位)
_RENDER_RULES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "text": ("文本", ("content", "title"), "(无内容)"),
    "quote": ("文本", ("content", "quoteContent", "title"), "(无内容)"),
    "reply": ("文本", ("content", "quoteContent", "title"), "(无内容)"),
    "image": ("图片", ("title", "content"), "[图片]"),
    "image_group": ("图片", ("title", "content"), "[图片]"),
    "voice": ("语音", ("voiceTranscript", "content"), "[语音]"),
    "audio": ("语音", ("voiceTranscript", "content"), "[语音]"),
    "video": ("视频", ("title", "content"), "[视频]"),
    "short_video": ("视频", ("title", "content"), "[视频]"),
    "emoji": ("表情", ("content", "title"), "[表情]"),
    "sticker": ("表情", ("content", "title"), "[表情]"),
    "link": ("链接/文件", ("title", "url", "content"), "[链接]"),
    "file": ("链接/文件", ("title", "content"), "[文件]"),
    "attachment": ("链接/文件", ("title", "content"), "[文件]"),
    "system": ("系统", ("content", "title"), "[系统消息]"),
    "notice": ("系统", ("content", "title"), "[系统消息]"),
    "revoke": ("系统", ("content", "title"), "[撤回消息]"),
}

# 本地消息类型兜底（API 未给 renderType 时）
_LOCAL_TYPE_FALLBACK = {
    1: "text",
    3: "image",
    34: "voice",
    43: "video",
    47: "emoji",
    49: "link",
    10000: "system",
}


def _clean_name(value: Any) -> str:
    text = str(value or "")
    for char in _IGNORED_NAME_CHARS:
        text = text.replace(char, "")
    return text.strip()


def _clean_text(value: Any, max_len: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_len]


def _pick_text(row: dict[str, Any], keys: tuple[str, ...], placeholder: str) -> str:
    for key in keys:
        value = _clean_text(row.get(key))
        if value:
            if key == "url":
                return f"[链接] {value}"
            return value
    return placeholder


def from_raw_row(chat_id: str, row: dict[str, Any]) -> StructuredMessage:
    """从 WeChatDataAnalysis 原始消息行构建 StructuredMessage。"""

    timestamp = int(row.get("createTime", 0) or 0)
    render_type = str(row.get("renderType") or "").strip().lower()
    if not render_type:
        try:
            render_type = _LOCAL_TYPE_FALLBACK.get(int(row.get("type", 0) or 0), "text")
        except (TypeError, ValueError):
            render_type = "text"
    msg_type, text_keys, placeholder = _RENDER_RULES.get(render_type, _RENDER_RULES["text"])

    raw_id = str(row.get("id") or "").strip()
    if not raw_id:
        seed = "|".join(
            [
                chat_id,
                str(timestamp),
                str(row.get("senderUsername", "") or ""),
                str(row.get("content", "") or ""),
            ]
        )
        raw_id = "m_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]

    sender = _clean_name(row.get("senderDisplayName"))
    if not sender or sender == "我":
        sender = _clean_name(row.get("senderUsername")) or "unknown"

    return StructuredMessage(
        id=raw_id,
        timestamp=timestamp,
        time=datetime.fromtimestamp(timestamp).strftime("%m-%d %H:%M"),
        sender=sender,
        text=_pick_text(row, text_keys, placeholder),
        msg_type=msg_type,
        render_type=render_type,
        chat_id=chat_id,
    )


def from_raw_rows(chat_id: str, rows: list[dict[str, Any]]) -> list[StructuredMessage]:
    """批量转换，按时间排序并做 (timestamp, sender, type, text) 去重。"""

    messages: list[StructuredMessage] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        message = from_raw_row(chat_id, row)
        fingerprint = (message.timestamp, message.sender, message.msg_type, message.text)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        messages.append(message)
    messages.sort(key=lambda item: (item.timestamp, item.id))
    return messages


def to_llm_text(messages: list[StructuredMessage]) -> str:
    """把消息列表拼成 LLM 可直接阅读的纯文本块。"""

    return "\n".join(message.to_llm_line() for message in messages)
