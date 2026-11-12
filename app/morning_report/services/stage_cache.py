"""阶段结果缓存（V0.6.1 §5.3）：输入指纹命中才复用，12h 有效期，新轮生成时清理。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from ..models import StageCache

CST = timezone(timedelta(hours=8))


def fingerprint(*parts) -> str:
    """输入依赖（资讯快照、个人上下文、模型、prompt 版本等）序列化哈希。"""

    canonical = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def get_cached(mr: Session, node_key: str, fp: str) -> dict | None:
    row = mr.execute(
        sa_select(StageCache).where(
            StageCache.node_key == node_key, StageCache.fingerprint == fp
        ).order_by(StageCache.id.desc())
    ).scalars().first()
    if row is None:
        return None
    if row.expires_at <= _now():
        mr.delete(row)
        mr.commit()
        return None
    return row.output


def put_cache(mr: Session, node_key: str, fp: str, output: dict,
              ttl_hours: int = 12, model: str = "", prompt_version: str = "v1") -> None:
    mr.add(StageCache(
        node_key=node_key, fingerprint=fp, output=output, model=model,
        prompt_version=prompt_version,
        created_at=_now(),
        expires_at=(datetime.now(CST) + timedelta(hours=ttl_hours)).isoformat(),
    ))
    mr.commit()


def clear_expired(mr: Session) -> int:
    rows = mr.execute(
        sa_delete(StageCache).where(StageCache.expires_at <= _now())
    ).rowcount
    mr.commit()
    return rows or 0


def clear_all(mr: Session) -> int:
    """每天 08:00 新一轮生成开始时清理（不删除新闻/向量/正式日志）。"""

    rows = mr.execute(sa_delete(StageCache)).rowcount
    mr.commit()
    return rows or 0


def _now() -> str:
    return datetime.now(CST).isoformat()
