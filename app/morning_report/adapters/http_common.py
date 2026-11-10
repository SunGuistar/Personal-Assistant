"""HTTP 获取公共件：超时、有限重试（最多 2 次、指数退避）、统一 UA（httpx，项目标准）。"""

from __future__ import annotations

import logging
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
                return r.text
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < MAX_RETRIES:
            wait = 2 ** attempt  # 1s, 2s
            logger.warning("获取失败(%s)，%ss 后重试: %s", last, wait, url)
            time.sleep(wait)
    raise FetchError(url, last)
