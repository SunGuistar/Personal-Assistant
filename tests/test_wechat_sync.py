"""微信同步集成测试（阶段 3.6，按用户调整一/二的验证要求）。

FakeClient 模拟 WeChatDataAnalysis 分页行为（desc、客户端时间过滤）；
FakeEmbedding 计数断言"零重复向量/部分新增不全量"；
raw/normalized/chroma/hub.db 全部落在 pytest 临时目录，真实数据零接触。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from alembic import command
from alembic.config import Config

from app.models import SyncCursor
from app.services import wechat_service
from app.wechat_agent.data_api.message_store import MessageStore
from app.wechat_agent.data_api.normalize_snapshot import NORMALIZED_SCHEMA, _ensure_schema
from app.wechat_agent.normal_tools import rag_store

ROOT_DIR = Path(__file__).resolve().parent.parent
CHAT = "10086@chatroom"
DAY1 = int(datetime(2026, 11, 1, 10, 0, 0).timestamp())
DAY2 = int(datetime(2026, 11, 2, 10, 0, 0).timestamp())


def _row(msg_id: str, ts: int, text: str) -> dict:
    return {
        "id": msg_id,
        "createTime": ts,
        "senderUsername": "u1",
        "senderDisplayName": "Alice",
        "renderType": "text",
        "content": text,
    }


class FakeClient:
    """模拟 API：按 desc 分页 + 客户端时间过滤（与真实 iter_messages 语义一致）。"""

    def __init__(self, rows: list[dict]):
        self.rows = sorted(rows, key=lambda r: (int(r["createTime"]), str(r["id"])), reverse=True)

    def iter_messages(self, username, *, start_ts: int, end_ts: int, batch_size: int = 500):
        for row in self.rows:
            ts = int(row["createTime"])
            if start_ts <= ts <= end_ts:
                yield row


class FakeEmbedding:
    """确定性向量 + 调用计数。"""

    def __init__(self) -> None:
        self.calls = 0
        self.documents = 0
        self.fail_next = False

    def name(self) -> str:
        return "fake-embedding"

    def __call__(self, input):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("embedding service down")
        self.calls += 1
        self.documents += len(input)
        return [[0.01] * 64 for _ in input]


@pytest.fixture()
def hub_session(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'hub.db'}"
    os.environ["PH_DATABASE_URL"] = db_url
    command.upgrade(Config(str(ROOT_DIR / "alembic.ini")), "head")
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    """raw/normalized/chroma 全部重定向到临时目录。"""
    raw = tmp_path / "chat_snapshot.sqlite3"
    normalized = tmp_path / "chat_snapshot_normalized.sqlite3"
    with MessageStore(raw):
        pass  # __init__ 已建 schema
    normalized_con = sqlite3.connect(normalized)
    _ensure_schema(normalized_con)
    normalized_con.close()

    monkeypatch.setattr(wechat_service, "RAW_DB_PATH", raw)
    monkeypatch.setattr(wechat_service, "NORMALIZED_DB_PATH", normalized)
    # rag_store 经 WECHAT_AGENT_DB 环境变量读归一化库，必须指向临时副本
    monkeypatch.setenv("WECHAT_AGENT_DB", str(normalized))

    fake_ef = FakeEmbedding()
    monkeypatch.setattr(rag_store, "CHROMA_DIR", tmp_path / "chroma_db")
    rag_store._client.cache_clear()
    monkeypatch.setattr(rag_store, "_embedding_function", lambda: fake_ef)
    return {"raw": raw, "normalized": normalized, "ef": fake_ef, "tmp": tmp_path}


def _normalized_count(path: Path) -> int:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("SELECT count(*) FROM messages").fetchone()[0]
    finally:
        con.close()


def _sync(hub_session, client, **kwargs):
    return wechat_service.sync_chat(hub_session, client, CHAT, "测试群", **kwargs)


def test_incremental_sync_and_overlap_idempotent(hub_session, isolated_store):
    rows = [_row(f"m{i}", DAY1 + i * 60, f"消息{i}") for i in range(10)]
    client = FakeClient(rows)

    first = _sync(hub_session, client, now_ts=DAY1 + 3600)
    assert first == {"fetched": 10, "new": 10}
    cursor = hub_session.get(SyncCursor, CHAT)
    assert (cursor.last_timestamp, cursor.last_msg_id) == (DAY1 + 9 * 60, "m9")

    # 第二次同步：重叠重传同样行 → 零新增、零重复
    second = _sync(hub_session, client, now_ts=DAY1 + 3600)
    assert second["new"] == 0
    assert _normalized_count(isolated_store["normalized"]) == 10


def test_same_second_late_message_caught_by_overlap(hub_session, isolated_store):
    rows = [_row(f"m{i}", DAY1 + i * 60, f"消息{i}") for i in range(5)]
    _sync(hub_session, FakeClient(rows), now_ts=DAY1 + 3600)

    # 同秒迟到消息（id 更大）计入新增；更早的迟到消息在重叠窗口内被幂等吸收
    late = rows + [_row("m5", DAY1 + 4 * 60, "同秒迟到"), _row("m6", DAY1 - 60, "窗口内迟到")]
    result = _sync(hub_session, FakeClient(late), now_ts=DAY1 + 3600)
    assert result["new"] == 1
    assert result["fetched"] == 7
    assert _normalized_count(isolated_store["normalized"]) == 7


def test_cursor_not_advanced_on_failure(hub_session, isolated_store, monkeypatch):
    rows = [_row(f"m{i}", DAY1 + i * 60, f"消息{i}") for i in range(3)]
    original = wechat_service.normalize_chat
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("normalized write failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(wechat_service, "normalize_chat", flaky)
    with pytest.raises(RuntimeError, match="normalized write failed"):
        _sync(hub_session, FakeClient(rows), now_ts=DAY1 + 3600)

    assert hub_session.get(SyncCursor, CHAT) is None  # 游标未推进
    assert _normalized_count(isolated_store["normalized"]) == 0

    # 重试安全：不重复、可恢复
    retry = _sync(hub_session, FakeClient(rows), now_ts=DAY1 + 3600)
    assert retry["new"] == 3
    assert _normalized_count(isolated_store["normalized"]) == 3


def test_duplicate_reexport_deduped_by_fingerprint(hub_session, isolated_store):
    rows = [_row("old_id", DAY1, "重复内容"), _row("m1", DAY1 + 60, "正常")]
    _sync(hub_session, FakeClient(rows), now_ts=DAY1 + 3600)
    # 同一消息被重新导出（新 id，同时间同内容）→ 归一化层去重，不产生重复行
    reexport = [_row("new_id", DAY1, "重复内容"), _row("m2", DAY1 + 120, "新消息")]
    result = _sync(hub_session, FakeClient(reexport), now_ts=DAY1 + 3600)
    assert result["new"] == 1
    assert _normalized_count(isolated_store["normalized"]) == 3


def test_reconcile_fixes_day_mismatch(hub_session, isolated_store):
    rows = [_row(f"m{i}", DAY1 + i * 60, f"消息{i}") for i in range(5)]
    _sync(hub_session, FakeClient(rows), now_ts=DAY1 + 3600)

    # 人为制造归一化库缺行（模拟历史异常）
    con = sqlite3.connect(isolated_store["normalized"])
    con.execute("DELETE FROM messages WHERE message_id = 'm2'")
    con.commit()
    con.close()

    fixed = wechat_service.reconcile_chat(hub_session, CHAT, "测试群")
    assert fixed == ["2026-11-01"]
    assert _normalized_count(isolated_store["normalized"]) == 5


def test_resync_range_refreshes_content(hub_session, isolated_store):
    rows = [_row("m1", DAY1, "旧内容")]
    _sync(hub_session, FakeClient(rows), now_ts=DAY1 + 3600)

    updated = FakeClient([_row("m1", DAY1, "修正后内容")])
    count = wechat_service.resync_range(hub_session, updated, CHAT, "测试群", start="2026-11-01", end="2026-11-01")
    assert count == 1
    con = sqlite3.connect(f"file:{isolated_store['normalized']}?mode=ro", uri=True)
    text = con.execute("SELECT text FROM messages WHERE message_id='m1'").fetchone()[0]
    con.close()
    assert text == "修正后内容"


def test_index_zero_reembed_on_empty_and_partial_only(hub_session, isolated_store):
    rows_day1 = [_row(f"d1_{i}", DAY1 + i * 60, f"第一天{i}") for i in range(8)]
    client = FakeClient(rows_day1)
    wechat_service.run_sync_job(hub_session, client, chat_id=CHAT, display_name="测试群")
    first_docs = isolated_store["ef"].documents
    assert first_docs > 0

    # 无新消息：整 job 重跑 → 零 Embedding
    isolated_store["ef"].calls = 0
    wechat_service.run_sync_job(hub_session, client, chat_id=CHAT, display_name="测试群")
    assert isolated_store["ef"].calls == 0

    # 部分新增：只嵌入新 chunk，不全群重建
    rows_day2 = rows_day1 + [_row(f"d2_{i}", DAY2 + i * 60, f"第二天{i}") for i in range(3)]
    before = isolated_store["ef"].documents
    wechat_service.run_sync_job(hub_session, FakeClient(rows_day2), chat_id=CHAT, display_name="测试群")
    delta = isolated_store["ef"].documents - before
    total = _normalized_count(isolated_store["normalized"])
    assert 0 < delta < total  # 远小于全量（total 条消息）


def test_index_write_failure_recovery(hub_session, isolated_store):
    rows = [_row(f"m{i}", DAY1 + i * 60, f"消息{i}") for i in range(6)]
    result = wechat_service.run_sync_job(hub_session, FakeClient(rows), chat_id=CHAT, display_name="测试群")
    assert result["index"][CHAT] > 0
    chunks_ok = rag_store._collection().count()

    # 新消息 + Embedding 故障：incremental_index 对单群失败记 -1 并跳过，
    # 旧索引完好，job 整体不崩
    rows_more = rows + [_row("m9", DAY2, "新消息")]
    isolated_store["ef"].fail_next = True
    failed = wechat_service.run_sync_job(hub_session, FakeClient(rows_more), chat_id=CHAT, display_name="测试群")
    assert failed["index"][CHAT] == -1
    assert rag_store._collection().count() == chunks_ok  # 旧索引未被破坏

    # 恢复后重试：尾部增量补齐（边界 chunk 重切：旧尾 chunk 被替换，总数可持平），
    # 不重复嵌入已有 chunk
    before = isolated_store["ef"].documents
    retried = wechat_service.run_sync_job(hub_session, FakeClient(rows_more), chat_id=CHAT, display_name="测试群")
    assert retried["index"][CHAT] > 0
    assert rag_store._collection().count() >= chunks_ok
    docs = rag_store._collection().get(include=["documents"])["documents"]
    assert any("新消息" in doc for doc in docs)  # 新消息已被索引
    delta = isolated_store["ef"].documents - before
    total = _normalized_count(isolated_store["normalized"])
    assert 0 < delta < total
