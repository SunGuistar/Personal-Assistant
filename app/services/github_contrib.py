"""GitHub 贡献统计（Personal Hub 口径，非 GitHub 官方 Contributions）。

统计口径（确定性代码，无 LLM；文案口径与代码一致）：
- 某天贡献数 = 当天（Asia/Shanghai）作者时间归属的 commit 数
  + 当天创建的 PR 数 + 当天创建的 Issue 数。
- 时间存储为 UTC ISO 文本，归属日与展示时间统一转 +08:00 计算——
  UTC 年末与 +08 年末不同步的边界天然正确。
- 与 GitHub 官方口径的差异（默认分支限制、提交归属规则、review 等计入方式）
  不做对齐；本模块结果只代表"本地已同步数据的个人活动统计"。

颜色等级：0 → 0 次；1-2 → L1；3-5 → L2；6-8 → L3；≥9 → L4（固定阈值，可测）。
覆盖范围：取三类数据时间字段的 min/max；完全没有数据时返回 synced=False，
由前端区分"尚未同步"与"零贡献"，不把缺失数据显示为 0 贡献。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GithubCommit, GithubIssue, GithubPullRequest, GithubRepo

SH_TZ = ZoneInfo("Asia/Shanghai")

LEVEL_THRESHOLDS = (1, 3, 6, 9)  # L1/L2/L3/L4 下限

COUNTING_NOTE = (
    "Personal Hub 口径：当天（Asia/Shanghai）作者提交的 commit 数 + 当天创建的 PR 数 "
    "+ 当天创建的 Issue 数；与 GitHub 官方 Contributions 统计规则不同"
)


def level_of(count: int) -> int:
    if count <= 0:
        return 0
    for level in range(4, 0, -1):
        if count >= LEVEL_THRESHOLDS[level - 1]:
            return level
    return 0


def _parse_utc(value: str | None) -> datetime | None:
    """ISO8601 UTC 文本（含 Z）→ aware datetime；无法解析返回 None（不伪造）。"""

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def sh_date(value: str | None) -> date | None:
    parsed = _parse_utc(value)
    return parsed.astimezone(SH_TZ).date() if parsed else None


def sh_datetime_text(value: str | None) -> str:
    """展示时间（+08:00，秒级）。"""
    parsed = _parse_utc(value)
    if parsed is None:
        return ""
    return parsed.astimezone(SH_TZ).isoformat(timespec="seconds")


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    start = datetime(year, 1, 1, tzinfo=ZoneInfo("UTC"))
    end = datetime(year + 1, 1, 1, tzinfo=ZoneInfo("UTC"))
    return start, end


def contributions_for_year(session: Session, year: int) -> dict:
    """年度每日贡献数 + 颜色等级 + 数据覆盖范围。"""
    start, end = _year_bounds(year)
    day_counts: dict[date, int] = {date(year, 1, 1) + timedelta(days=i): 0 for i in range(366 if _is_leap(year) else 365)}

    coverage_dates: list[date] = []

    commits = session.execute(
        select(GithubCommit).where(
            GithubCommit.authored_at >= start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            GithubCommit.authored_at < end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    ).scalars().all()
    for commit in commits:
        coverage_dates.append(sh_date(commit.authored_at) or date.min)
        day = sh_date(commit.authored_at)
        if day and day in day_counts:
            day_counts[day] += 1

    prs = session.execute(
        select(GithubPullRequest).where(
            GithubPullRequest.created_at >= start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            GithubPullRequest.created_at < end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    ).scalars().all()
    for pr in prs:
        coverage_dates.append(sh_date(pr.created_at) or date.min)
        day = sh_date(pr.created_at)
        if day and day in day_counts:
            day_counts[day] += 1

    issues = session.execute(
        select(GithubIssue).where(
            GithubIssue.created_at >= start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            GithubIssue.created_at < end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    ).scalars().all()
    for issue in issues:
        coverage_dates.append(sh_date(issue.created_at) or date.min)
        day = sh_date(issue.created_at)
        if day and day in day_counts:
            day_counts[day] += 1

    synced = bool(coverage_dates)
    days = [
        {"date": day.isoformat(), "count": count, "level": level_of(count)}
        for day, count in sorted(day_counts.items())
    ]
    return {
        "year": year,
        "total": sum(day_counts.values()),
        "days": days,
        "coverage": {
            "synced": synced,
            "from": min(coverage_dates).isoformat() if synced else None,
            "to": max(coverage_dates).isoformat() if synced else None,
        },
        "counting_note": COUNTING_NOTE,
    }


def day_detail(session: Session, day: date) -> dict:
    """指定 +08:0 日期的活动详情（commit / PR / Issue，按时间倒序）。"""

    repo_names = {
        row.id: row.full_name for row in session.execute(select(GithubRepo)).scalars().all()
    }

    def in_day(value: str | None) -> bool:
        return sh_date(value) == day

    commits = [
        {
            "type": "commit",
            "repo": repo_names.get(row.repo_id, ""),
            "title": (row.message or "").splitlines()[0][:120],
            "message": row.message,
            "time": sh_datetime_text(row.authored_at),
            "url": row.url,
        }
        for row in session.execute(select(GithubCommit)).scalars().all()
        if in_day(row.authored_at)
    ]
    prs = [
        {
            "type": "pull_request",
            "repo": repo_names.get(row.repo_id, ""),
            "title": row.title,
            "time": sh_datetime_text(row.created_at),
            "url": row.url,
        }
        for row in session.execute(select(GithubPullRequest)).scalars().all()
        if in_day(row.created_at)
    ]
    issues = [
        {
            "type": "issue",
            "repo": repo_names.get(row.repo_id, ""),
            "title": row.title,
            "time": sh_datetime_text(row.created_at),
            "url": row.url,
        }
        for row in session.execute(select(GithubIssue)).scalars().all()
        if in_day(row.created_at)
    ]

    items = sorted(commits + prs + issues, key=lambda item: item["time"], reverse=True)
    return {"date": day.isoformat(), "items": items}


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
