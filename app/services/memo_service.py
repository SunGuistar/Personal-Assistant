"""随手备忘业务逻辑：单份 Markdown 便签，存本地文件（不写 SQLite）。

存储：用户目录 `~/.personal-hub/memo.md`（可用 PH_USER_ENV_DIR 覆盖，与密钥
权威目录同规范）；UTF-8；不入 Git。

写入安全：
- 临时文件 + os.replace 原子替换（写入中断不损坏原文件）；
- 进程内锁 + 写入前内容比对：乱序到达的晚提交不会用旧内容覆盖新内容
  （比对失败返回冲突错误，由前端以最新内容重试）；
- 显式失败抛 DomainError，不假装成功。
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from ..exceptions import DomainError

logger = logging.getLogger(__name__)

MAX_MEMO_BYTES = 512 * 1024

_write_lock = threading.Lock()


def memo_path() -> Path:
    """备忘文件路径：用户目录（与 .env 权威文件同目录），不入库不入 Git。"""

    override = os.environ.get("PH_USER_ENV_DIR", "").strip()
    base = Path(override) if override else Path.home() / ".personal-hub"
    return base / "memo.md"


def read_memo(path: Path | None = None) -> str:
    """读取便签内容；文件不存在按空内容处理。"""

    target = path or memo_path()
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise DomainError(f"备忘读取失败: {exc}", code="memo_read_failed", status_code=500)
    if len(raw) > MAX_MEMO_BYTES:
        raise DomainError("备忘文件超过大小限制", code="memo_too_large", status_code=413)
    return raw.decode("utf-8", errors="replace")


def write_memo(content: str, path: Path | None = None, *, expected: str | None = None) -> None:
    """原子写入便签。expected 提供时已持久化内容与之不符则拒绝（防乱序覆盖）。"""

    data = content.encode("utf-8")
    if len(data) > MAX_MEMO_BYTES:
        raise DomainError("备忘内容超过 512KB 限制", code="memo_too_large", status_code=413)
    target = path or memo_path()

    with _write_lock:  # 串行化写入，避免并发交错
        if expected is not None:
            current = read_memo(target)
            if current != expected:
                raise DomainError(
                    "备忘内容已被其他修改覆盖，请刷新后重试",
                    code="memo_conflict",
                    status_code=409,
                )
        tmp: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + f".tmp-{os.getpid()}")
            tmp.write_bytes(data)
            os.replace(tmp, target)  # 原子替换
        except OSError as exc:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
            raise DomainError(f"备忘保存失败: {exc}", code="memo_write_failed", status_code=500)
