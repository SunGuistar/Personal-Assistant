"""Qdrant 存储层：双 Collection、幂等 upsert、Dense+Sparse 混合检索。

- 点 ID 用确定性哈希（sha1：key_prefix|content_hash），禁止随机 UUID（AGENTS §2）。
- 向量配置：dense cosine（1024 维）+ sparse（IDF modifier），与预检实测一致。
- 所有写操作幂等：同 ID 重投即覆盖更新。
"""

from __future__ import annotations

import hashlib
import logging

from qdrant_client import QdrantClient, models

from ..adapters.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)


def point_id(key_prefix: str, content_hash: str) -> int:
    digest = hashlib.sha1(f"{key_prefix}|{content_hash}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")  # uint64（Qdrant 接受无符号整数或 UUID）


class QdrantStore:
    def __init__(self, url: str, dense_dims: int = 1024, api_key: str = ""):
        self.client = QdrantClient(url=url, api_key=api_key or None, timeout=30)
        self.dense_dims = dense_dims

    # ---------- Collection 管理 ----------

    def ensure_collection(self, name: str) -> None:
        if self.client.collection_exists(name):
            return
        self.client.create_collection(
            name,
            vectors_config={"dense": models.VectorParams(size=self.dense_dims, distance=models.Distance.COSINE)},
            sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        logger.info("Qdrant Collection 已创建: %s", name)

    # ---------- 写入（幂等） ----------

    def upsert_documents(
        self,
        collection: str,
        docs: list[dict],
        provider: EmbeddingProvider,
    ) -> int:
        """docs: [{point_key, content_hash, text, payload}]；返回写入点数。

        text 用于向量化；payload 必须含可追溯字段（source_url 等）。
        """

        self.ensure_collection(collection)
        if not docs:
            return 0
        dense = provider.embed_dense([d["text"] for d in docs])
        sparse = provider.embed_sparse([d["text"] for d in docs])
        points = [
            models.PointStruct(
                id=point_id(d["point_key"], d["content_hash"]),
                vector={
                    "dense": dv,
                    "sparse": models.SparseVector(indices=si, values=sv),
                },
                payload=d["payload"],
            )
            for d, dv, (si, sv) in zip(docs, dense, sparse)
        ]
        self.client.upsert(collection, points=points)
        return len(points)

    def delete_by_key(self, collection: str, point_key: str, content_hash: str) -> None:
        self.client.delete(collection, points_selector=[point_id(point_key, content_hash)])

    # ---------- 检索 ----------

    def search_hybrid(
        self,
        collection: str,
        query_text: str,
        provider: EmbeddingProvider,
        limit: int = 8,
        filters: dict | None = None,
    ) -> list[dict]:
        """Dense+Sparse prefetch + RRF；filters 形如 {"report_date": "..."}（payload 等值过滤）。"""

        q_filter = None
        if filters:
            q_filter = models.Filter(must=[
                models.FieldCondition(key=k, match=models.MatchValue(value=v))
                for k, v in filters.items()
            ])
        qv = provider.embed_dense([query_text])[0]
        si, sv = provider.embed_sparse([query_text])[0]
        result = self.client.query_points(
            collection,
            prefetch=[
                models.Prefetch(query=qv, using="dense", limit=limit * 2,
                                filter=q_filter, score_threshold=None),
                models.Prefetch(query=models.SparseVector(indices=si, values=sv),
                                using="sparse", limit=limit * 2, filter=q_filter),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return [
            {"point_id": p.id, "score": p.score, "payload": p.payload or {}}
            for p in result.points
        ]

    def count(self, collection: str) -> int:
        if not self.client.collection_exists(collection):
            return 0
        return self.client.count(collection).count
