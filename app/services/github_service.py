"""GitHub 同步编排（阶段一）：全量 + 增量同步、游标、幂等 upsert。

- 游标复用 sync_cursors 表：scope=github:{full_name}，last_timestamp=上次成功
  同步时刻（epoch 秒）。commits 用 since（作者时间口径）；PR/Issue 的 since 作用
  于 updated_at——会把更早创建但近期更新的记录带回，upsert 幂等吸收，不影响计数。
- 幂等：commits 以 sha、PR/Issue 以 GitHub id 主键 merge；重复同步不产生重复行。
- 保守策略：GitHub 上已删除的仓库本地不删（删除走专门清理流程，禁止自动删除）。
- 个人贡献口径：只同步当前 Token 用户 owner 的仓库（list_repos 已限定 affiliation=owner）。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GithubCommit, GithubIssue, GithubPullRequest, GithubRepo, SyncCursor

logger = logging.getLogger(__name__)

SYNC_KIND = "github.sync"
_CURSOR_PREFIX = "github:"


class GithubSource(Protocol):
    """同步依赖的客户端最小接口（GithubClient/测试 FakeClient 均实现）。"""

    def list_repos(self) -> list[dict]: ...
    def iter_commits(self, full_name: str, since: str = "") -> Any: ...
    def iter_pull_requests(self, full_name: str, since: str = "") -> Any: ...
    def iter_issues(self, full_name: str, since: str = "") -> Any: ...


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cursor_since(session: Session, scope: str) -> str:
    cursor = session.get(SyncCursor, scope)
    if cursor is None or not cursor.last_timestamp:
        return ""
    return datetime.fromtimestamp(cursor.last_timestamp, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _advance_cursor(session: Session, scope: str, ts: int) -> None:
    cursor = session.get(SyncCursor, scope)
    if cursor is None:
        cursor = SyncCursor(scope=scope, last_timestamp=0, last_msg_id="")
        session.add(cursor)
    if ts > (cursor.last_timestamp or 0):
        cursor.last_timestamp = ts
    session.commit()


def upsert_repo(session: Session, fields: dict[str, Any]) -> None:
    existing = session.get(GithubRepo, fields["id"])
    if existing is None:
        session.add(GithubRepo(**fields, synced_at=_now()))
    else:
        for key, value in fields.items():
            setattr(existing, key, value)
        existing.synced_at = _now()


def run_sync_job(
    session: Session,
    client: GithubSource,
    *,
    progress_cb: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """同步任务体（TaskRunner 调用）。逐仓库提交，失败时已完成部分保留。"""

    def report(value: int) -> None:
        if progress_cb:
            progress_cb(value)

    from ..adapters.github_source import commit_fields, issue_fields, pull_fields, repo_fields

    repos_raw = client.list_repos()
    counts: dict[str, Any] = {"repos": len(repos_raw), "commits": 0, "pull_requests": 0, "issues": 0}

    total = max(len(repos_raw), 1)
    for index, raw_repo in enumerate(repos_raw):
        fields = repo_fields(raw_repo)
        full_name = fields["full_name"]
        since = _cursor_since(session, f"{_CURSOR_PREFIX}{full_name}")

        upsert_repo(session, fields)
        session.flush()

        for raw in client.iter_commits(full_name, since):
            data = commit_fields(raw)
            if not data["sha"]:
                continue
            session.merge(GithubCommit(repo_id=fields["id"], **data))
            counts["commits"] += 1

        for raw in client.iter_pull_requests(full_name, since):
            data = pull_fields(raw)
            if not data["id"]:
                continue
            session.merge(GithubPullRequest(repo_id=fields["id"], **data))
            counts["pull_requests"] += 1

        for raw in client.iter_issues(full_name, since):
            if "pull_request" in raw:  # issues 端点混含 PR（键可能为空对象），不计入 Issue
                continue
            data = issue_fields(raw)
            if not data["id"]:
                continue
            session.merge(GithubIssue(repo_id=fields["id"], **data))
            counts["issues"] += 1

        _advance_cursor(session, f"{_CURSOR_PREFIX}{full_name}", int(time.time()))
        report(int((index + 1) / total * 100))

    session.commit()
    logger.info("github sync done: %s", counts)
    return counts


def stats_summary(session: Session) -> dict[str, Any]:
    """GitHub 页状态区：各表行数与最近一次同步任务。"""

    from ..models import Task

    last_task = session.execute(
        select(Task).where(Task.kind == SYNC_KIND).order_by(Task.id.desc()).limit(1)
    ).scalars().first()

    return {
        "repos": session.query(GithubRepo).count(),
        "commits": session.query(GithubCommit).count(),
        "pull_requests": session.query(GithubPullRequest).count(),
        "issues": session.query(GithubIssue).count(),
        "last_sync": (
            {"status": last_task.status, "error": last_task.error, "updated_at": last_task.updated_at}
            if last_task
            else None
        ),
    }
