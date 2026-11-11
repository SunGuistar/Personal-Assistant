"""新浪页面公开点击榜：国内/国际各 20 条；核验实际榜单日期并保留排名证据。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import NewsCandidate
from .http_common import FetchError, fetch_text

API = "https://top.news.sina.com.cn/ws/GetTopDataList.php"
CATEGORIES = {"domestic": "news_china_suda", "international": "news_world_suda"}
CST = timezone(timedelta(hours=8))


def parse_hot(text: str, category: str, report_date: str, fetched_at: str) -> list[NewsCandidate]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise FetchError(API, "榜单响应不是 JSON/JS 数据")
    try:
        rows = json.loads(text[start:end + 1])["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FetchError(API, "榜单数据结构变化") from exc
    if not isinstance(rows, list) or not rows:
        raise FetchError(API, "榜单为空")
    requested = datetime.fromisoformat(report_date).date()
    out = []
    for rank, row in enumerate(rows[:20], 1):
        try:
            rank_date = datetime.strptime(str(row["top_time"]), "%Y%m%d").date()
        except (KeyError, ValueError, TypeError) as exc:
            raise FetchError(API, "缺少可靠榜单日期") from exc
        age = (requested - rank_date).days
        if age < 0 or age > 1:
            raise FetchError(API, "榜单日期超出允许范围（仅当天或前一天）")
        if not row.get("title") or not row.get("url"):
            continue
        published = None
        try:
            stamp = parsedate_to_datetime(row["time"])
            if stamp.tzinfo is not None:
                published = stamp.astimezone(CST).isoformat()
        except (KeyError, TypeError, ValueError):
            pass
        try:
            heat = int(str(row.get("top_num", "0")).replace(",", ""))
        except ValueError:
            heat = None
        out.append(NewsCandidate(
            category=category, title=row["title"].strip(), summary="",
            source_name=row.get("media") or "新浪新闻", source_url=row["url"],
            published_at=published, adapter="sina_hot",
            raw={"selection_kind": "hot", "rank": rank, "rank_value": heat,
                 "rank_date": rank_date.isoformat(), "requested_date": report_date,
                 "fetched_at": fetched_at, "stale_rank": age == 1,
                 "time_source": "sina_article_time" if published else "unknown"},
        ))
    if not out:
        raise FetchError(API, "榜单没有有效条目")
    return out


def fetch_hot(category: str, report_date: str) -> list[NewsCandidate]:
    params = {"top_type": "day", "top_cat": CATEGORIES[category],
              "top_time": report_date.replace("-", ""), "top_show_num": "20",
              "top_order": "DESC", "js_var": "news_"}
    fetched_at = datetime.now(CST).isoformat()
    return parse_hot(fetch_text(API, params=params), category, report_date, fetched_at)
