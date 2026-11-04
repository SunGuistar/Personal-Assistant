"""资讯适配器公共件：原始条目结构、HTTP 抓取（超时/有限重试/UA）。

遵守 AGENTS §6：外部调用必须设超时；重试最多 2 次、指数退避；
禁止无限重试与裸 except。适配器只负责"取数 + 解析为统一结构"，
去重/评分/落库在 service 层。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
MAX_RETRIES = 2  # 最多重试 2 次（共 3 次尝试），指数退避
MAX_ITEMS_PER_SOURCE = 100  # 单源单次抓取上限（低资源原则；大 feed 截断最新前 100 条）
USER_AGENT = "personal-assistant/0.1 (+local news reader)"


class NewsAdapterError(RuntimeError):
    """单个来源抓取/解析失败；由 service 层捕获，不影响其他来源。"""


@dataclass(frozen=True)
class RawNewsItem:
    """适配器输出的统一原始资讯条目。"""

    title: str
    url: str
    published_at: datetime  # 必须带时区（统一 UTC）
    raw_summary: str = ""
    heat_raw: float = 0.0
    extra: dict = field(default_factory=dict)


def fetch_bytes(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    client: httpx.Client | None = None,
) -> bytes:
    """GET 抓取（UA + 超时 + 有限重试）。client 可注入（测试用 respx 拦截）。"""

    headers = {"User-Agent": USER_AGENT}
    own_client = client is None
    http = client or httpx.Client(follow_redirects=True)
    try:
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = http.get(url, headers=headers, timeout=timeout)
                response.raise_for_status()
                return response.content
            except (httpx.HTTPError, OSError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(2**attempt)  # 1s、2s 指数退避
        raise NewsAdapterError(f"抓取失败（{max_retries + 1} 次尝试）: {last_exc}") from last_exc
    finally:
        if own_client:
            http.close()
