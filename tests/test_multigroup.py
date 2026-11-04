"""多群支持测试（阶段 3.5）：run_summary 按 chat_id 过滤、单群行为回归。

LLM 用 Fake（按 system 提示词区分 map/final 阶段），零付费调用；
数据库与输出目录全部在临时目录。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app.wechat_agent.chat_tools import summarizer
from app.wechat_agent.data_api.normalize_snapshot import NORMALIZED_SCHEMA
from app.wechat_agent.normal_tools import report_render

MAP_JSON = json.dumps({"summary": "时段概述", "topics": [{"title": "话题", "key_points": ["要点"], "quotes": []}]})
FINAL_JSON = json.dumps(
    {
        "summary": "总览",
        "highlights": ["要点1"],
        "topics": [{"title": "话题", "time_ranges": ["11-03 10:00-11:00"], "discussion": "讨论", "quotes": []}],
        "observations": [],
        "closing": "结尾",
    }
)


class FakeLLM:
    model_name = "fake-multigroup-test"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke(self, messages, **kwargs):
        system = messages[0][1]
        user = messages[1][1]
        self.calls.append({"system": system, "user": user})
        content = FINAL_JSON if "撰写最终日报" in system else MAP_JSON

        class _Response:
            pass

        response = _Response()
        response.content = content
        return response


def _build_two_chat_db(path: Path) -> None:
    con = sqlite3.connect(path)
    for statement in NORMALIZED_SCHEMA:
        con.execute(statement)
    chats = [("chat_A", "群甲"), ("chat_B", "群乙")]
    for chat_id, name in chats:
        con.execute(
            "INSERT INTO chats(chat_id, display_name, normalized_at) VALUES (?, ?, 'x')", (chat_id, name)
        )
        # 2026-11-03 10:00 起两条消息/群
        base = int(datetime(2026, 11, 3, 10, 0, 0).timestamp())
        for index in range(2):
            con.execute(
                """INSERT INTO messages(message_id, chat_id, timestamp, time, sender, text, msg_type, render_type)
                   VALUES (?, ?, ?, ?, ?, ?, '文本', 'text')""",
                (f"{chat_id}_m{index}", chat_id, base + index * 60, "11-03 10:0" + str(index), "某人", f"{name}的消息{index}"),
            )
    con.commit()
    con.close()


@pytest.fixture()
def multi_chat_db(tmp_path):
    db = tmp_path / "normalized.sqlite3"
    _build_two_chat_db(db)
    return db


@pytest.fixture(autouse=True)
def fake_pipeline(monkeypatch, tmp_path):
    fake = FakeLLM()
    monkeypatch.setattr(summarizer, "_build_llm", lambda: fake)
    monkeypatch.setattr(summarizer, "OUTPUT_ROOT", tmp_path / "Output")
    monkeypatch.setattr(report_render, "export_png", lambda html_path, png_path: False)
    return fake


def test_run_summary_filters_by_chat_id(multi_chat_db, fake_pipeline):
    paths = summarizer.run_summary("2026-11-03", db_path=multi_chat_db, chat_id="chat_B")
    html = Path(paths["html"]).read_text(encoding="utf-8")
    assert "群乙" in html
    assert "群甲" not in html
    # final 阶段的输入只包含群乙的消息
    final_call = fake_pipeline.calls[-1]
    assert "群乙" in final_call["user"]
    assert "群甲的消息" not in final_call["user"]


def test_run_summary_multi_group_requires_chat_id(multi_chat_db):
    with pytest.raises(RuntimeError, match="chat_id"):
        summarizer.run_summary("2026-11-03", db_path=multi_chat_db)


def test_unknown_chat_id_rejected(multi_chat_db):
    with pytest.raises(RuntimeError, match="找不到群"):
        summarizer.run_summary("2026-11-03", db_path=multi_chat_db, chat_id="no_such")


def test_single_group_without_chat_id_still_works(tmp_path, fake_pipeline):
    db = tmp_path / "single.sqlite3"
    _build_two_chat_db(db)
    con = sqlite3.connect(db)
    con.execute("DELETE FROM messages WHERE chat_id = 'chat_A'")
    con.execute("DELETE FROM chats WHERE chat_id = 'chat_A'")
    con.commit()
    con.close()

    paths = summarizer.run_summary("2026-11-03", db_path=db)  # 不传 chat_id
    assert "群乙" in Path(paths["html"]).read_text(encoding="utf-8")
