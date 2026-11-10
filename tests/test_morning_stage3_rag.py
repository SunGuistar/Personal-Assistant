# -*- coding: utf-8 -*-
"""阶段 3 验收：Qdrant 双 Collection、混合检索、Embedding 复用、阶段缓存、索引一致性。

用真本地 Qdrant（127.0.0.1）+ tmp_mr_ 前缀 Collection（用后清理）；Embedding 用假实现。
"""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import select

from app.morning_report.adapters.embedding import content_hash
from app.morning_report.models import IndexState, NewsItem, ReportVersion, StageCache
from app.morning_report.services import index_sync, stage_cache
from app.morning_report.services.qdrant_store import QdrantStore
from app.morning_report.services.rag_tool import IndexUnavailableError, RagTool

COL_TECH = f"tmp_mr_tech_{uuid.uuid4().hex[:8]}"
COL_REPORTS = f"tmp_mr_reports_{uuid.uuid4().hex[:8]}"


class FakeProvider:
    dims = 8
    model_name = "fake-embed-v1"

    def embed_dense(self, texts):
        # 确定性伪向量：按文本字符和编码（同文本同向量，便于命中断言）
        out = []
        for t in texts:
            v = [0.0] * self.dims
            for i, ch in enumerate(t):
                v[i % self.dims] += (ord(ch) % 7) / 7.0
            out.append(v)
        return out

    def embed_sparse(self, texts):
        out = []
        for t in texts:
            idx = sorted({ord(ch) % 64 for ch in t})
            out.append((idx, [1.0] * len(idx)))
        return out


@pytest.fixture()
def store():
    s = QdrantStore(url="http://127.0.0.1:6333", dense_dims=8)
    yield s
    for col in (COL_TECH, COL_REPORTS):
        if s.client.collection_exists(col):
            s.client.delete_collection(col)


def _seed_items(mr, run_id, n=3):
    for i in range(n):
        mr.add(NewsItem(
            run_id=run_id, category="ai", title=f"LangGraph 技巧第{i}条",
            summary=f"关于状态图与检查点的实践总结 {i}",
            source_name="GitHub", source_url=f"https://example.com/{i}",
            published_at="2026-11-09T10:00:00+08:00",
            content_hash=f"h{i}", dedupe_status="unique", raw_ref={},
        ))
    mr.commit()


def test_sync_and_hybrid_search(fclient, store):
    provider = FakeProvider()
    with fclient.app.state.mr_session_factory() as mr:
        run = mr.execute(select(NewsItem.run_id)).first()  # noqa
    with fclient.app.state.mr_session_factory() as mr:
        # 先造一个 collect run
        from app.morning_report.services import news_pipeline
        r = news_pipeline.create_collect_run(mr, "2026-11-10")
        _seed_items(mr, r.id)
        summary = index_sync.sync_tech_news(mr, store, provider, r.id, COL_TECH)
    assert summary["indexed"] == 3
    assert summary["consistency"] == "ok"

    hits = store.search_hybrid(COL_TECH, "LangGraph 检查点", provider, limit=3)
    assert len(hits) == 3
    assert all(h["payload"]["source_url"].startswith("https://example.com/") for h in hits)
    # 确定性 ID 幂等：重复 upsert 不增加点数
    with fclient.app.state.mr_session_factory() as mr:
        index_sync.sync_tech_news(mr, store, provider, r.id, COL_TECH)
    assert store.count(COL_TECH) == 3


def test_embedding_cache_reuse(fclient, store):
    provider = FakeProvider()
    from app.morning_report.adapters.embedding import cached_embed
    from app.morning_report.models import EmbeddingCache

    with fclient.app.state.mr_session_factory() as mr:
        a = cached_embed(mr, provider, ["同一段文本", "另一段文本"])
        assert len(a) == 2
        rows = mr.execute(select(EmbeddingCache)).scalars().all()
        assert len(rows) == 2
        # 第二次同样文本：缓存命中，不新增（无重复 Embedding 调用）
        b = cached_embed(mr, provider, ["同一段文本"])
        assert b[0] == a[0]
        rows = mr.execute(select(EmbeddingCache)).scalars().all()
        assert len(rows) == 2


def test_rag_tool_rewrite_fallback_and_blocking(fclient, store):
    provider = FakeProvider()
    with fclient.app.state.mr_session_factory() as mr:
        from app.morning_report.services import news_pipeline
        r = news_pipeline.create_collect_run(mr, "2026-11-10")
        _seed_items(mr, r.id, n=2)
        index_sync.sync_tech_news(mr, store, provider, r.id, COL_TECH)

        calls = {"n": 0}

        def rewrite(q):
            calls["n"] += 1
            return q + " 改写"

        tool = RagTool(store, provider, fclient.app.state.mr_session_factory, llm_rewrite=rewrite)
        res = tool.search(COL_TECH, "状态图", limit=2)
        assert res.used_rewrite and calls["n"] == 1
        assert len(res.results) == 2

        # 改写失败 → 回退基础检索
        def bad_rewrite(q):
            raise RuntimeError("改写服务不可用")
        tool2 = RagTool(store, provider, fclient.app.state.mr_session_factory, llm_rewrite=bad_rewrite)
        res2 = tool2.search(COL_TECH, "检查点", limit=2)
        assert res2.used_rewrite is False and len(res2.results) == 2

        # 索引状态 dirty → 阻塞
        row = mr.execute(select(IndexState).where(IndexState.collection_name == COL_TECH)).scalars().first()
        row.status = "dirty"
        mr.commit()
        tool3 = RagTool(store, provider, fclient.app.state.mr_session_factory)
        with pytest.raises(IndexUnavailableError):
            tool3.search(COL_TECH, "状态图")


def test_stage_cache_ttl_and_clear(fclient):
    with fclient.app.state.mr_session_factory() as mr:
        fp = stage_cache.fingerprint("资讯A", {"memory": 1})
        assert stage_cache.get_cached(mr, "info_analysis", fp) is None
        stage_cache.put_cache(mr, "info_analysis", fp, {"result": "ok"}, ttl_hours=12)
        assert stage_cache.get_cached(mr, "info_analysis", fp) == {"result": "ok"}
        # 不同指纹不命中
        assert stage_cache.get_cached(mr, "info_analysis", stage_cache.fingerprint("资讯B")) is None
        # 过期即失效
        stage_cache.put_cache(mr, "info_analysis", fp + "x", {"r": 1}, ttl_hours=0)
        time.sleep(0.01)
        assert stage_cache.get_cached(mr, "info_analysis", fp + "x") is None
        # 新轮清理
        n = stage_cache.clear_all(mr)
        assert n >= 1
        assert stage_cache.get_cached(mr, "info_analysis", fp) is None


def test_report_version_chunking_and_sync(fclient, store):
    provider = FakeProvider()
    md = "# 今日晨报\n\n## 一、开篇速览\n\n今天值得关注。\n\n## 二、重要资讯\n\n### 国内\n\n某政策出台。\n\n### AI\n\n新模型发布。\n"
    with fclient.app.state.mr_session_factory() as mr:
        from app.morning_report.services import news_pipeline
        r = news_pipeline.create_collect_run(mr, "2026-11-10")
        ver = ReportVersion(run_id=r.id, report_date="2026-11-10", version_no=1,
                            is_primary=True, status="published", title="晨报",
                            sections={}, content_md=md, snapshot_id="snap-1")
        mr.add(ver)
        mr.commit()
        summary = index_sync.sync_report_version(mr, store, provider, ver.id, COL_REPORTS)
    assert summary["chunks"] == 5  # 标题树：晨报/开篇/重要资讯/国内/AI
    hits = store.search_hybrid(COL_REPORTS, "新模型", provider, limit=2,
                               filters={"report_date": "2026-11-10"})
    assert hits and hits[0]["payload"]["version_id"] == ver.id
    with fclient.app.state.mr_session_factory() as mr:
        problems = index_sync.check_required_indexes(mr, store, [COL_REPORTS])
    assert problems == []


def test_required_index_check_detects_missing(fclient, store):
    from sqlalchemy.orm import Session

    with fclient.app.state.mr_session_factory() as mr:
        problems = index_sync.check_required_indexes(mr, store, ["tmp_mr_definitely_missing_zzz"])
    assert problems and "missing" in problems[0]
