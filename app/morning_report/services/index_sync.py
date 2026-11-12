"""索引同步：AI 资讯 → morning_tech_news；晨报版本 → morning_reports；一致性检查。

- 幂等：点 ID = 确定性哈希，重复同步即覆盖；增量（按 content_hash 判断是否需要重算向量，
  命中 EmbeddingCache 则不重复调用 Embedding API）。
- 一致性：同步后核对 SQLite 记录数与 Qdrant 点数，并维护 index_state；
  检查不通过置 dirty/failed（RagTool 据此阻塞工作流）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters.embedding import EmbeddingProvider, content_hash
from ..models import IndexState, NewsItem, ReportVersion
from .qdrant_store import QdrantStore

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def _touch_state(mr: Session, collection: str, status: str, note: str = "") -> None:
    row = mr.execute(
        select(IndexState).where(IndexState.collection_name == collection)
    ).scalars().first()
    if row is None:
        row = IndexState(collection_name=collection)
        mr.add(row)
    row.status = status
    row.note = note[:300]
    row.last_synced_at = datetime.now(CST).isoformat()
    mr.commit()


def sync_tech_news(mr: Session, store: QdrantStore, provider: EmbeddingProvider,
                   run_id: int, collection: str) -> dict:
    """把当期 AI 资讯（含全文/摘要文本）写入 tech_news Collection。"""

    items = mr.execute(
        select(NewsItem).where(NewsItem.run_id == run_id, NewsItem.category == "ai")
    ).scalars().all()
    docs = []
    for it in items:
        text = f"{it.title}\n{it.summary or ''}".strip()
        docs.append({
            "point_key": f"ai:{it.id}",
            "content_hash": content_hash(text),
            "text": text,
            "payload": {
                "news_item_id": it.id, "title": it.title, "summary": it.summary,
                "source_name": it.source_name, "source_url": it.source_url,
                "published_at": it.published_at, "run_id": run_id,
                "content_hash": content_hash(text),
            },
        })
    written = store.upsert_documents(collection, docs, provider)
    summary = {"ai_items": len(items), "indexed": written}
    _verify(mr, store, collection, len(items), summary)
    return summary


def split_sections(content_md: str) -> list[tuple[str, str]]:
    """把晨报正文按一级/二级标题切成语义单元（历史检索片段）。"""

    import re

    parts: list[tuple[str, str]] = []
    matches = list(re.finditer(r"^(#{1,3})\s+(.+)$", content_md, re.M))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content_md)
        parts.append((m.group(2).strip(), content_md[m.start():end].strip()))
    if not parts and content_md.strip():
        parts.append(("全文", content_md.strip()))
    return parts


def sync_report_version(mr: Session, store: QdrantStore, provider: EmbeddingProvider,
                        version_id: int, collection: str) -> dict:
    """把已发布晨报版本的分块写入 reports Collection（供历史语义检索）。"""

    ver = mr.get(ReportVersion, version_id)
    if ver is None:
        raise ValueError(f"report version {version_id} 不存在")
    docs = []
    for heading, chunk in split_sections(ver.content_md):
        docs.append({
            "point_key": f"report:{ver.id}",
            "content_hash": content_hash(f"{ver.id}|{heading}|{chunk}"),
            "text": chunk,
            "payload": {
                "report_date": ver.report_date, "version_id": ver.id,
                "version_no": ver.version_no, "is_primary": ver.is_primary,
                "heading": heading, "snapshot_id": ver.snapshot_id,
                "content_hash": content_hash(f"{ver.id}|{heading}|{chunk}"),
            },
        })
    written = store.upsert_documents(collection, docs, provider)
    summary = {"version_id": ver.id, "chunks": written}
    _touch_state(mr, collection, "ok", f"sync report v{ver.id}")
    return summary


def _verify(mr: Session, store: QdrantStore, collection: str,
            expected: int, summary: dict) -> None:
    actual = store.count(collection)
    if actual < expected:
        note = f"点数 {actual} < 期望 {expected}（可能含历史点，属正常增量场景）"
        _touch_state(mr, collection, "dirty", note)
        summary["consistency"] = "dirty"
    else:
        _touch_state(mr, collection, "ok", f"sync ok, points={actual}")
        summary["consistency"] = "ok"
    summary["points"] = actual


def check_required_indexes(mr: Session, store: QdrantStore,
                           collections: list[str]) -> list[str]:
    """生成前置检查：返回不可用 Collection 列表（空=通过）。"""

    problems = []
    for name in collections:
        row = mr.execute(
            select(IndexState).where(IndexState.collection_name == name)
        ).scalars().first()
        if row is not None and row.status in ("failed", "dirty"):
            problems.append(f"{name}({row.status})")
        elif not store.client.collection_exists(name):
            problems.append(f"{name}(missing)")
    return problems
