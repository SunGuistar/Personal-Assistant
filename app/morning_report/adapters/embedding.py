"""向量生成：Dense（DashScope text-embedding-v4，OpenAI 兼容端点）+ Sparse（fastembed BM25）。

- EmbeddingProvider 协议便于测试注入假实现（零外网零付费）。
- DashScope batch 要求 ≤10 且为 2 的幂（T13 实测），这里固定 batch=8。
- fastembed 模型懒加载；首次运行需下载模型文件（本机一次性）。
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

DASHSCOPE_EMBED_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"


def content_hash(text: str) -> str:
    norm = " ".join(text.split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


class EmbeddingProvider(Protocol):
    dims: int
    model_name: str

    def embed_dense(self, texts: list[str]) -> list[list[float]]: ...
    def embed_sparse(self, texts: list[str]) -> list[tuple[list[int], list[float]]]: ...


class DashScopeDense:
    """text-embedding-v4；key 从环境读取（env_bootstrap 已加载），异常向外抛由调用方降级。"""

    def __init__(self, model: str = "text-embedding-v4", batch_size: int = 8):
        self.model_name = model
        self.dims = 1024
        self._batch = batch_size

    def embed_dense(self, texts: list[str]) -> list[list[float]]:
        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not key:
            raise RuntimeError("DASHSCOPE_API_KEY 未配置")
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            batch = texts[i:i + self._batch]
            with httpx.Client(timeout=60) as client:
                r = client.post(
                    DASHSCOPE_EMBED_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": self.model_name, "input": batch},
                )
            r.raise_for_status()
            data = r.json()["data"]
            data.sort(key=lambda d: d["index"])
            out.extend([d["embedding"] for d in data])
        return out


class FastembedSparse:
    """Qdrant/bm25 本地 sparse 编码（懒加载）。"""

    def __init__(self, model: str = "Qdrant/bm25"):
        self.model_name = f"sparse:{model}"
        self.dims = 0  # sparse 无固定维度
        self._model = None
        self._model_id = model

    def _ensure(self):
        if self._model is None:
            from fastembed import SparseTextEmbedding

            logger.info("加载 sparse 模型 %s（首次可能下载）", self._model_id)
            self._model = SparseTextEmbedding(model_name=self._model_id)

    def embed_sparse(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        self._ensure()
        out = []
        for vec in self._model.embed(texts):
            out.append((list(vec.indices), list(vec.values)))
        return out


class DefaultEmbeddingProvider:
    """组合实现：dense 走 DashScope，sparse 走 fastembed。"""

    def __init__(self, dense: DashScopeDense | None = None, sparse: FastembedSparse | None = None):
        self._dense = dense or DashScopeDense()
        self._sparse = sparse or FastembedSparse()

    @property
    def dims(self) -> int:
        return self._dense.dims

    @property
    def model_name(self) -> str:
        return self._dense.model_name

    def embed_dense(self, texts: list[str]) -> list[list[float]]:
        return self._dense.embed_dense(texts)

    def embed_sparse(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        return self._sparse.embed_sparse(texts)


def cached_embed(
    mr,
    provider: EmbeddingProvider,
    texts: list[str],
) -> list[list[float]]:
    """Embedding 复用：同内容哈希 + 同模型命中缓存则不重复调用（V0.6.1 §5.3，独立于阶段缓存）。"""

    from ..models import EmbeddingCache
    from sqlalchemy import select as sa_select

    results: list[list[float] | None] = [None] * len(texts)
    todo_idx: list[int] = []
    hashes = [content_hash(t) for t in texts]
    rows = mr.execute(
        sa_select(EmbeddingCache).where(
            EmbeddingCache.content_hash.in_(hashes), EmbeddingCache.model == provider.model_name
        )
    ).scalars().all()
    by_hash = {r.content_hash: r.vector for r in rows}
    for i, h in enumerate(hashes):
        if h in by_hash:
            results[i] = by_hash[h]
        else:
            todo_idx.append(i)
    if todo_idx:
        vecs = provider.embed_dense([texts[i] for i in todo_idx])
        for i, vec in zip(todo_idx, vecs):
            results[i] = vec
            mr.add(EmbeddingCache(
                content_hash=hashes[i], model=provider.model_name,
                dims=len(vec), vector=vec,
            ))
        mr.commit()
    return [r for r in results if r is not None]
