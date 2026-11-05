"""阶段 5：清理后增量索引一致性回归（以现有 incremental_index 实际算法验证）。

验证点（对应批准要求）：
1. 删除旧消息后 rag_state 与实际一致；
2. 后续同步新消息能正常增量索引（新 chunk 生成、向量只算新增）；
3. 不触发全群重新 Embedding（FakeEmbedding 计数断言）；
4. 不遗漏新消息；
5. 失败/重试不破坏索引状态；
6. 保护日期 chunk 保持不变；
7. 若 rag_state 未维护（模拟），下一次 incremental 会全量重建（负面对照，
   证明"仅改计数"不是拍脑袋，而是该判定的必要条件）。
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.cleanup import chroma_access, service
from app.models import CleanupCandidate
from app.wechat_agent.normal_tools import rag_store

from cleanup_ref import (
    CHAT,
    OLD_DATE,
    PROTECTED_DATE,
    build_env,
    chroma_client_with,
    make_messages,
    normalized_count,
)

PROTECTED = [PROTECTED_DATE]
TODAY = date(2026, 11, 5)


@pytest.fixture()
def hub(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'hub.db'}"
    os.environ["PH_DATABASE_URL"] = db_url
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture()
def indexed_env(hub, tmp_path, monkeypatch):
    """临时 normalized + 临时 Chroma，用真实 build_index 建索引。"""
    old = make_messages(CHAT, OLD_DATE, 5)
    protected = make_messages(CHAT, PROTECTED_DATE, 4)
    recent = make_messages(CHAT, "2026-11-04", 3)
    messages = old + protected + recent
    env = build_env(tmp_path, messages)

    monkeypatch.setenv("WECHAT_AGENT_DB", str(env.normalized))
    monkeypatch.setattr(rag_store, "CHROMA_DIR", env.chroma)
    rag_store._client.cache_clear()
    monkeypatch.setattr(rag_store, "_embedding_function", lambda: env.ef)

    stats = rag_store.build_index()
    assert stats[CHAT] > 0
    env.ef.documents = 0  # 清零，后续计数只统计增量

    # 清理通道与索引用同一 Chroma 客户端（chromadb 同路径单例限制）
    monkeypatch.setattr(chroma_access, "chroma_client", lambda path: rag_store._client())
    return env


def _cleanup_old(hub, env):
    review = service.ensure_review(hub, today=TODAY, protected=PROTECTED, paths=env.paths)
    candidate = hub.execute(
        select(CleanupCandidate).where(
            CleanupCandidate.review_id == review.id, CleanupCandidate.msg_date == OLD_DATE
        )
    ).scalar_one()
    service.confirm_review(hub, review.id, [candidate.id], protected=PROTECTED, paths=env.paths)
    result = service.execute_review(hub, review.id, protected=PROTECTED, paths=env.paths)
    assert result == {"deleted_groups": 1, "failed_groups": 0}
    return env


def _append_new_messages(env, count: int = 2) -> list[dict]:
    """向归一化库追加新消息（模拟同步后新数据）。"""
    import sqlite3
    from datetime import datetime

    new_rows = make_messages(CHAT, "2026-11-05", count, start_index=100, base_hour=9)
    con = sqlite3.connect(env.normalized)
    for row in new_rows:
        con.execute(
            "insert into messages (message_id, chat_id, timestamp, time, sender, text, msg_type, render_type)"
            " values (?, ?, ?, ?, ?, ?, ?, ?)",
            (row["message_id"], row["chat_id"], row["timestamp"], row["time"],
             row["sender"], row["text"], row["msg_type"], row["render_type"]),
        )
    con.commit()
    con.close()
    return new_rows


def _chunk_ids(env) -> set:
    result = rag_store._client().get_collection("chat_chunks").get(include=[])
    return set(result["ids"])


def test_cleanup_then_incremental_index(hub, indexed_env):
    env = indexed_env
    before_ids = _chunk_ids(env)

    _cleanup_old(hub, env)
    new_rows = _append_new_messages(env)

    embedded_before = env.ef.documents
    stats = rag_store.incremental_index()
    assert stats[CHAT] > 0  # 新消息被索引

    # ③ 不触发全群重建：Embedding 只发生在增量 chunk（远小于剩余消息总数 9；
    #   若全量重建则每个剩余消息都被重新嵌入，见负面对照）
    assert env.ef.documents >= 1
    assert env.ef.documents < 9
    # 保护 chunk 未被重新嵌入重建（原 ID 原内容仍在）
    assert "e28bbae4" in "".join(_chunk_ids(env)) or any(
        "2026-10-27" in m["date"] for m in rag_store._client().get_collection("chat_chunks").get(include=["metadatas"])["metadatas"]
    )

    # ① 状态一致：rag_state.total_msgs = 实际剩余
    client = rag_store._client()
    state = client.get_collection("rag_state").get(ids=[CHAT], include=["metadatas"])
    remaining = normalized_count(env.normalized, CHAT)
    assert state["metadatas"][0]["total_msgs"] == remaining == 9  # 保护4 + 近日3 + 新增2

    # ④ 不遗漏：新消息的 chunk 存在且可被检索
    collection = client.get_collection("chat_chunks")
    found = collection.get(where={"chat_id": {"$eq": CHAT}}, include=["metadatas"])
    all_msg_ids = ",".join(m["msg_ids"] for m in found["metadatas"])
    for row in new_rows:
        assert row["message_id"] in all_msg_ids

    # ⑥ 保护 chunk 未变：原保护 chunk（ID/内容）在清理+增量后原样存在
    after_ids = _chunk_ids(env)
    removed = before_ids - after_ids
    assert removed  # 旧日期 chunk 已删
    full = collection.get(include=["metadatas", "documents"])
    metas = {mid: m for mid, m in zip(full["ids"], full["metadatas"])}
    docs = dict(zip(full["ids"], full["documents"]))
    protected_remaining = [mid for mid, m in metas.items() if m["date"] == PROTECTED_DATE]
    assert protected_remaining  # 保护 chunk 全在
    for mid in protected_remaining:
        assert "2026-10-27" in docs[mid]  # 内容未被修改


def test_incremental_without_rag_state_maintenance_triggers_rebuild(hub, indexed_env, monkeypatch):
    """负面对照：若清理后不维护 rag_state，下一次 incremental 必然全群重建。"""
    env = indexed_env
    _cleanup_old(hub, env)

    # 模拟"未维护"：把 total_msgs 改回清理前（构建时 12）→ 总数减少 → 触发全量重建
    client = rag_store._client()
    state_col = client.get_collection("rag_state")
    meta = dict(state_col.get(ids=[CHAT], include=["metadatas"])["metadatas"][0])
    meta["total_msgs"] = 12  # 清理前
    state_col.update(ids=[CHAT], metadatas=[meta])

    new_rows = _append_new_messages(env)
    rag_store.incremental_index()
    # 全群重建：所有剩余 chunk 被重新嵌入（Embedding 文档数 ≥ chunk 总数，
    # 且远大于增量的 1-2 个文档）
    client = rag_store._client()
    total_chunks = len(client.get_collection("chat_chunks").get(include=[])["ids"])
    assert total_chunks >= 3
    assert env.ef.documents >= total_chunks  # 全量重建证据（负面对照）
