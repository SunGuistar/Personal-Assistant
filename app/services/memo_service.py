"""旧版随手备忘文件（memo.md）读取与一次性迁移。

随手备忘已改为 SQLite 多条记录（memos 表，见 memos_service）。本模块仅保留：
- memo_path()/read_memo()：旧文件读取（迁移前不得停用）；
- migrate_legacy_memo()：把旧 Markdown 内容作为一条备忘导入 SQLite（幂等）。

保护原则：不删除、不清空原文件；导入以固定标题判重，重复运行不生成重复记录。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..exceptions import DomainError
from ..models import Memo

logger = logging.getLogger(__name__)

MAX_MEMO_BYTES = 512 * 1024

# 迁移记录的固定标题（判重依据）
MIGRATED_TITLE = "【迁移】旧版随手备忘"


def memo_path() -> Path:
    """旧备忘文件路径：用户目录（与 .env 同目录）。"""

    override = os.environ.get("PH_USER_ENV_DIR", "").strip()
    base = Path(override) if override else Path.home() / ".personal-hub"
    return base / "memo.md"


def read_memo(path: Path | None = None) -> str:
    """读取旧便签文件；文件不存在/为空按空内容处理。"""

    target = path or memo_path()
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise DomainError(f"旧备忘读取失败: {exc}", code="memo_read_failed", status_code=500)
    if len(raw) > MAX_MEMO_BYTES:
        raise DomainError("旧备忘文件超过大小限制", code="memo_too_large", status_code=413)
    return raw.decode("utf-8", errors="replace")


def migrate_legacy_memo(session: Session, path: Path | None = None) -> bool:
    """把旧 memo.md 内容导入为一条随手备忘（幂等：按固定标题判重）。

    返回是否执行了导入。不删除/不改写原文件；文件为空或已迁移则直接返回。
    """

    content = read_memo(path).strip()
    if not content:
        return False
    exists = session.execute(select(Memo.id).where(Memo.title == MIGRATED_TITLE)).first()
    if exists:
        return False
    max_order = session.execute(select(Memo.sort_order).order_by(Memo.sort_order.desc())).scalars().first()
    session.add(Memo(title=MIGRATED_TITLE, content=content, sort_order=(max_order or 0) + 1))
    session.commit()
    logger.info("旧版随手备忘已迁移为一条记录（title=%s，%d 字）", MIGRATED_TITLE, len(content))
    return True
