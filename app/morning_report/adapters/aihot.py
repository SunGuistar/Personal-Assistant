"""AIHOT 最新日报接入（V2.1：/api/v1/dailies/latest 为 AI 资讯唯一生产入口）。

- 日报归属依据 report.date == report_date；日期不符/结构异常/HTTP 失败一律 FetchError，
  由采集管线走来源失败降级，不允许旧日报冒充当期。
- 条目收录依据是"属于当期日报"而非逐条原文发布时间在本地窗口内：
  日报归属窗口（daily_window_*）与原文发布时间（published_at）分开记录，禁止混用。
- 展示链接优先 links.original，缺失时用有效的 links.aihot；只接受 http/https，不编造链接。
- 旧 /api/v1/items 精选接口（fetch_selected）保留供历史数据兼容，不再进入生产采集。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urldefrag, urlsplit, urlunsplit

from . import NewsCandidate
from .http_common import FetchError, fetch_text

logger = logging.getLogger(__name__)

API = "https://aihot.news/api/v1/items"  # 旧精选接口（仅历史兼容，生产不再调用）
DAILY_API = "https://aihot.news/api/v1/dailies/latest"
CST = timezone(timedelta(hours=8))
MAX_PAGES = 10  # 防御：单轮最多翻 10 页


def _to_cst(iso: str) -> str | None:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(CST).isoformat()


def _valid_link(url) -> str | None:
    """只接受有效 http/https 链接；其余（空/非字符串/非 http 协议）一律丢弃，不编造。"""

    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return url


def _norm_key(url: str | None) -> str | None:
    """去重键：规范化链接（小写协议/域名、去 fragment、去末尾斜杠）。"""

    if not url:
        return None
    try:
        base, _frag = urldefrag(url)
        parts = urlsplit(base)
        norm = urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                           parts.path.rstrip("/") or "/", parts.query, ""))
        return norm
    except ValueError:
        return None


def parse_daily_report(body: dict, report_date: str) -> list[NewsCandidate]:
    """解析最新日报：sections.items（按原分类顺序）→ flashes → highlights 去重补入。

    lead/highlights 只做重点标记；lead 若无可验证条目链接，不凭标题构造链接、不新增条目。
    """

    report = body.get("report") if isinstance(body, dict) else None
    if not isinstance(report, dict):
        raise FetchError(DAILY_API, "日报结构异常（缺少 report 对象）")
    daily_date = report.get("date")
    if daily_date != report_date:
        raise FetchError(DAILY_API, f"日报日期不符：期望 {report_date}，实际 {daily_date}")
    sections = report.get("sections")
    if not isinstance(sections, list):
        raise FetchError(DAILY_API, "日报结构异常（sections 缺失或类型错误）")
    flashes = report.get("flashes") or []
    highlights = report.get("highlights") or []
    if not isinstance(flashes, list) or not isinstance(highlights, list):
        raise FetchError(DAILY_API, "日报结构异常（flashes/highlights 类型错误）")

    daily_meta = {"daily_date": daily_date, "daily_member": True,
                  "daily_window_start": report.get("windowStart"),
                  "daily_window_end": report.get("windowEnd"),
                  "daily_generated_at": report.get("generatedAt")}
    lead = report.get("lead") or {}
    lead_title = (lead.get("title") or "").strip() if isinstance(lead, dict) else ""

    out: list[NewsCandidate] = []
    seen: set[str] = set()
    order = 0

    def add(entry, kind: str, label: str) -> None:
        nonlocal order
        if not isinstance(entry, dict):
            return
        title = (entry.get("title") or "").strip()
        if not title:
            return
        links = entry.get("links") or {}
        original = _valid_link(links.get("original"))
        aihot_link = _valid_link(links.get("aihot"))
        display_url = original or aihot_link or ""
        key = _norm_key(display_url) or ("title:" + title.lower())
        if key in seen:
            return
        seen.add(key)
        order += 1
        out.append(NewsCandidate(
            category="ai", title=title,
            summary=(entry.get("summary") or "").strip(),
            source_name=(entry.get("source") or {}).get("name") or "AIHOT",
            source_url=display_url,
            published_at=_to_cst(entry["publishedAt"]) if entry.get("publishedAt") else None,
            adapter="aihot",
            raw={**daily_meta, "daily_kind": kind, "section_label": label,
                 "display_order": order, "aihot_url": aihot_link or "",
                 "original_url": original or "",
                 "is_lead": bool(lead_title and lead_title == title)},
        ))

    for section in sections:
        if not isinstance(section, dict):
            continue
        label = (section.get("label") or "").strip() or "未分类"
        items = section.get("items")
        if not isinstance(items, list):
            raise FetchError(DAILY_API, f"日报结构异常（栏目 {label} 的 items 类型错误）")
        for entry in items:
            add(entry, "section", label)
    for entry in flashes:
        add(entry, "flash", "快讯")
    for entry in highlights:
        add(entry, "highlight", "精选")

    if not out:
        raise FetchError(DAILY_API, "日报没有任何可展示条目")
    return out


def fetch_daily(report_date: str) -> list[NewsCandidate]:
    """获取当期 AIHOT 日报；日期不符/结构异常/HTTP 失败抛 FetchError。"""

    try:
        body = json.loads(fetch_text(DAILY_API))
    except ValueError as exc:
        raise FetchError(DAILY_API, "日报响应不是 JSON") from exc
    return parse_daily_report(body, report_date)


# ---------- 旧精选接口（历史兼容，生产采集已停用，不得作为日报快照） ----------

def fetch_selected(limit_per_page: int = 50, max_pages: int = MAX_PAGES) -> list[NewsCandidate]:
    """旧 /api/v1/items 精选列表（仅保留历史兼容，禁止在生产采集使用）。"""

    out: list[NewsCandidate] = []
    cursor: str | None = None
    for _ in range(max_pages):
        params: dict = {"mode": "selected", "window": "24h", "limit": str(limit_per_page)}
        if cursor:
            params["cursor"] = cursor
        body = json.loads(fetch_text(API, params=params))
        for item in body.get("items", []):
            links = item.get("links") or {}
            out.append(NewsCandidate(
                category="ai",
                title=(item.get("title") or "").strip(),
                summary=(item.get("summary") or "").strip(),
                source_name=(item.get("source") or {}).get("name") or (item.get("source") or {}).get("title") or "AIHOT",
                source_url=links.get("original") or links.get("url") or "",
                published_at=_to_cst(item["publishedAt"]) if item.get("publishedAt") else None,
                adapter="aihot",
                raw={"item_id": item.get("id"), "discovered_at": item.get("discoveredAt")},
            ))
        page = body.get("page") or {}
        if not page.get("hasMore") or not page.get("nextCursor"):
            break
        cursor = page["nextCursor"]
    return out
