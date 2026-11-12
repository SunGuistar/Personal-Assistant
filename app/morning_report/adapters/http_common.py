"""HTTP 获取公共件：超时、有限重试（最多 2 次、指数退避）、统一 UA（httpx，项目标准）。"""

from __future__ import annotations

import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

UA = {"User-Agent": "personal-hub-morning-report/2.0 (+personal use)"}
DEFAULT_TIMEOUT = 20.0
MAX_RETRIES = 2  # AGENTS §5：重试最多 2 次


class FetchError(RuntimeError):
    def __init__(self, url: str, reason: str):
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason


def fetch_text(url: str, *, timeout: float = DEFAULT_TIMEOUT, params: dict | None = None) -> str:
    """GET 并返回文本；失败重试后仍失败抛 FetchError（429/5xx/超时/连接错）。"""

    last = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                r = client.get(url, params=params, headers=UA)
            if r.status_code == 200:
                # httpx 默认 UTF-8；HTML 页面常仅在 meta 中声明 GB2312。
                if "charset=" not in r.headers.get("content-type", "").lower():
                    declared = re.search(rb"charset\s*=\s*[\"\']?([a-zA-Z0-9_-]+)", r.content[:4096], re.I)
                    if declared:
                        encoding = declared[1].decode("ascii").lower()
                        if encoding in ("gb2312", "gbk", "gb18030"):
                            encoding = "gb18030"
                        try:
                            return r.content.decode(encoding)
                        except (LookupError, UnicodeError):
                            pass
                return r.text
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < MAX_RETRIES:
            wait = 2 ** attempt  # 1s, 2s
            logger.warning("获取失败(%s)，%ss 后重试: %s", last, wait, url)
            time.sleep(wait)
    raise FetchError(url, last)
