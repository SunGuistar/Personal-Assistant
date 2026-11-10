"""统一 RAG Tool：三个 Subagent 共用（V0.6 §4.3 / V0.6.1 §5.2）。

- 基础模式：Dense+BM25 混合检索，返回可追溯来源（payload 含 source_url/report 版本）。
- 按需增强：Query 改写（LLM，失败自动回退基础检索并记录）；Rerank 默认关闭（T21：真实
  Reranker 无可用服务，收益不显著），保留开关便于将来接入。
- 必要索引不存在/不一致时抛 IndexUnavailableError（由工作流转为阻塞，不允许绕过）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ...exceptions import DomainError
from ..models import IndexState
from .qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


class IndexUnavailableError(DomainError):
    """必要索引缺失或不一致——工作流必须阻塞，不得回退绕过。"""

    def __init__(self, message: str):
        super().__init__(message, code="index_unavailable", status_code=409)


@dataclass
class RagResult:
    collection: str
    results: list[dict] = field(default_factory=list)
    rewritten_query: str | None = None
    used_rewrite: bool = False
    used_rerank: bool = False


class RagTool:
    def __init__(
        self,
        store: QdrantStore,
        provider,
        mr_session_factory,
        llm_rewrite=None,  # callable(prompt:str)->str；None=改写不可用
        reranker=None,  # callable(query, docs)->docs；None=不启用
    ):
        self.store = store
        self.provider = provider
        self._sf = mr_session_factory
        self._llm_rewrite = llm_rewrite
        self._reranker = reranker

    def check_index_available(self, collection: str) -> None:
        """必要索引检查：Collection 不存在或 index_state 标记 failed/dirty → 阻塞。"""

        from sqlalchemy import select as sa_select

        if self.store.count(collection) == 0 and not self.store.client.collection_exists(collection):
            raise IndexUnavailableError(f"必要索引不存在: {collection}")
        with self._sf() as mr:
            row = mr.execute(
                sa_select(IndexState).where(IndexState.collection_name == collection)
            ).scalars().first()
        if row is not None and row.status in ("failed", "dirty"):
            raise IndexUnavailableError(f"索引状态异常({row.status}): {collection} {row.note or ''}")

    def search(
        self,
        collection: str,
        query: str,
        limit: int = 8,
        filters: dict | None = None,
        allow_enhance: bool = True,
    ) -> RagResult:
        self.check_index_available(collection)
        out = RagResult(collection=collection)
        effective = query
        if allow_enhance and self._llm_rewrite is not None:
            try:
                rewritten = self._llm_rewrite(query)
                if rewritten and rewritten.strip():
                    effective = rewritten.strip()
                    out.rewritten_query = effective
                    out.used_rewrite = True
            except Exception as exc:
                logger.warning("Query 改写失败，回退基础检索: %s", f"{type(exc).__name__}: {exc}"[:150])
        out.results = self.store.search_hybrid(
            collection, effective, self.provider, limit=limit, filters=filters
        )
        if allow_enhance and self._reranker is not None and out.results:
            try:
                out.results = self._reranker(effective, out.results)[:limit]
                out.used_rerank = True
            except Exception as exc:
                logger.warning("Rerank 失败，保留原排序: %s", f"{type(exc).__name__}: {exc}"[:150])
        return out
