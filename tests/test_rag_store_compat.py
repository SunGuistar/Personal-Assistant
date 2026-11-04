"""rag_store.index_exists() 兼容性复现测试（F2，阶段 3 前置修复）。

chroma>=1.5 的 list_collections() 返回 Collection 对象而非字符串，
旧实现 `c == COLLECTION_NAME` 恒为 False，导致 index_exists() 误报。
本测试在临时 ephemeral 客户端上复现，修复后应为 True/False 正确反映。
"""

from __future__ import annotations

import chromadb

from app.wechat_agent.normal_tools import rag_store


def _ephemeral_with_chat_chunks():
    client = chromadb.EphemeralClient(settings=chromadb.Settings(anonymized_telemetry=False))
    # index_exists 只做集合名存在性判断，无需 Embedding（避免依赖 API Key）
    client.get_or_create_collection(name=rag_store.COLLECTION_NAME)
    return client


def test_index_exists_true_when_collection_present(monkeypatch):
    monkeypatch.setattr(rag_store, "_client", lambda: _ephemeral_with_chat_chunks())
    assert rag_store.index_exists() is True  # 修复前此处复现：恒 False


def test_index_exists_false_when_collection_missing(monkeypatch):
    # chroma 1.5 的 EphemeralClient 按进程共享内存态（不同实例可见同一集合），
    # 故用不存在的集合名验证 False 分支；注意先建集合再改 COLLECTION_NAME
    client = _ephemeral_with_chat_chunks()
    monkeypatch.setattr(rag_store, "_client", lambda: client)
    monkeypatch.setattr(rag_store, "COLLECTION_NAME", "no_such_collection")
    assert rag_store.index_exists() is False
