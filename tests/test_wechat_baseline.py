"""微信 Agent 回归测试基线（阶段 3.1）：迁移前后必须全绿且一致。

覆盖：工具注册与 docstring、chunk 确定性、归一化去重排序、
报告渲染结构与转义、真实库只读冒烟（临时副本，WECHAT_AGENT_DB 覆盖）。
全程零付费调用：不触发 LLM/Embedding（build_agent 仅构建不调用）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from env_bootstrap import load_hub_env

load_hub_env()  # 确保 build_agent 能读到用户目录的 Key（仅构建，不调用）

from tests.wechat_ref import (  # noqa: E402
    ALL_TOOLS,
    MIGRATED,
    build_agent,
    build_system_prompt,
    chunk_messages,
    from_raw_rows,
    render_html,
    to_llm_text,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
REAL_NORMALIZED = ROOT_DIR / "GetWechatInfo" / "DataInfo" / "chat_snapshot_normalized.sqlite3"

EXPECTED_TOOL_NAMES = [
    "list_chats",
    "get_stats",
    "get_messages",
    "search_messages",
    "semantic_search_messages",
    "get_messages_by_ids",
    "count_speakers_by_ids",
    "summarize_chat",
]

EXPECTED_PROMPT_FRAGMENTS = [
    "分多次",  # 系统提示词关键约束：分时段多次取数
    "summarize_chat",
    "semantic_search_messages",
]


# ---------- 工具与提示词 ----------

def test_tool_registry_unchanged():
    names = [tool.name for tool in ALL_TOOLS]
    assert names == EXPECTED_TOOL_NAMES


def test_tool_docstrings_present():
    # docstring 即提示词：迁移后必须保持（关键片段存在性检查）
    by_name = {tool.name: tool for tool in ALL_TOOLS}
    assert "分多次" in by_name["get_messages"].description
    assert "语义" in by_name["semantic_search_messages"].description
    assert "summarize_chat" in by_name["summarize_chat"].description or "总结" in by_name["summarize_chat"].description


def test_build_agent_constructs():
    agent = build_agent()
    assert agent is not None
    prompt = build_system_prompt()
    for fragment in EXPECTED_PROMPT_FRAGMENTS:
        assert fragment in prompt


# ---------- 纯函数行为 ----------

def _rows(*pairs):
    return [
        {
            "id": f"msg_{index}",
            "createTime": ts,
            "senderUsername": "u1",
            "senderDisplayName": " Alice ",
            "renderType": "text",
            "content": content,
        }
        for index, (ts, content) in enumerate(pairs)
    ]


def test_from_raw_rows_dedup_and_sort():
    rows = _rows((200, "第二条"), (100, "第一条"), (100, "第一条"))
    messages = from_raw_rows("chat_x", rows)
    assert [m.text for m in messages] == ["第一条", "第二条"]
    assert [m.id for m in messages] == ["msg_1", "msg_0"]
    assert to_llm_text(messages).splitlines()[0].endswith("第一条")


def test_chunk_messages_deterministic():
    rows = _rows(*[(100 + i * 60, f"消息{i}") for i in range(40)])
    messages = [m.__dict__ for m in from_raw_rows("chat_x", rows)]
    norm_rows = [
        {
            "message_id": m["id"],
            "chat_id": "chat_x",
            "timestamp": m["timestamp"],
            "time": m["time"],
            "sender": m["sender"],
            "text": m["text"],
            "msg_type": m["msg_type"],
        }
        for m in messages
    ]
    first = chunk_messages(norm_rows)
    second = chunk_messages(norm_rows)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]  # 确定性 ID
    assert len(first) > 1  # 40 条消息必然切成多个 chunk


def test_render_html_structure_and_escaping():
    report = {
        "chat_name": "群A",
        "date": "2026-11-03",
        "summary": "总览<b>",
        "highlights": ["要点1"],
        "topics": [
            {
                "title": "话题1",
                "time_ranges": ["11-03 10:00-11:00"],
                "discussion": "讨论内容",
                "quotes": [{"sender": "甲", "time": "11-03 10:05", "text": "原话"}],
            }
        ],
        "observations": ["观察1"],
        "activity": {"message_count": 10, "participant_count": 2, "type_counts": {"文本": 10}, "top_senders": []},
        "closing": "结尾",
    }
    html = render_html(report)
    for section in ("今日总览", "今日速览", "今日主要话题", "AI 今日观察", "今日活跃情况", "报告结尾"):
        assert section in html
    assert "<b>" not in html  # 注入已转义
    assert "&lt;b&gt;" in html


# ---------- 真实库只读冒烟（临时副本） ----------

@pytest.fixture()
def normalized_copy(tmp_path):
    """复制真实归一化库到临时目录（真实库零写入），供只读工具冒烟。"""

    target = tmp_path / "normalized.sqlite3"
    source = sqlite3.connect(f"file:{REAL_NORMALIZED}?mode=ro", uri=True)
    dest = sqlite3.connect(target)
    source.backup(dest)
    source.close()
    dest.close()
    monkey_target = str(target)
    old = __import__("os").environ.get("WECHAT_AGENT_DB")
    __import__("os").environ["WECHAT_AGENT_DB"] = monkey_target
    yield monkey_target
    if old is None:
        __import__("os").environ.pop("WECHAT_AGENT_DB", None)
    else:
        __import__("os").environ["WECHAT_AGENT_DB"] = old


def test_readonly_smoke_on_real_copy(normalized_copy):
    from tests.wechat_ref import ALL_TOOLS as _  # noqa: F401

    by_name = {tool.name: tool for tool in ALL_TOOLS}
    chats = by_name["list_chats"].invoke({})
    assert "钻粉群" in chats or "@chatroom" in chats

    stats = by_name["get_stats"].invoke({"date": "2026-11-01"})
    assert "条消息" in stats or "没有消息" in stats

    found = by_name["search_messages"].invoke({"keyword": "的", "limit": 5})
    assert "找到" in found or "没有找到" in found
