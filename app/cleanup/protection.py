"""永久保护日期规则（阶段 5 最高优先级）。

- 保护日期按消息实际本地时间解释，时区固定 Asia/Shanghai（不随机器时区变化）；
- 保护配置来自 Settings.protected_dates（PH_PROTECTED_DATES 可扩展）；
- 所有删除入口（候选/确认/执行/重试）都必须经过这里，禁止绕过。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))  # Asia/Shanghai（无夏令时）


def date_of_ts(ts: int) -> str:
    """消息时间戳 → Asia/Shanghai 本地日期 YYYY-MM-DD。"""

    return datetime.fromtimestamp(int(ts), SHANGHAI).date().isoformat()


def day_bounds(date_str: str) -> tuple[int, int]:
    """某日本地时间的 [开始, 结束) epoch 秒区间（Asia/Shanghai）。"""

    day = date.fromisoformat(date_str)
    start = datetime.combine(day, time.min, tzinfo=SHANGHAI)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def is_protected_date(date_str: str, protected: list[str]) -> bool:
    return date_str in protected


def group_key_of_ts(ts: int) -> str:
    """候选分组键：消息归属的 (date) 由调用方拼接 chat_id。"""

    return date_of_ts(ts)


def week_sunday(today: date) -> date:
    """本周审核所属周日：today 为周日则今天，否则回退到上一个周日。"""

    return today - timedelta(days=(today.weekday() + 1) % 7)


def is_cleanup_age(date_str: str, today: date, keep_days: int = 7) -> bool:
    """是否早于"今天前 keep_days 天"的清理边界（严格早于）。"""

    return date.fromisoformat(date_str) < today - timedelta(days=keep_days)
