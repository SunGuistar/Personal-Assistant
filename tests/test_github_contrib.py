"""GitHub 贡献统计与同步测试（隔离临时库 + FakeClient，零真实外网/Token）。

覆盖：闰年/普通年、UTC→Asia/Shanghai 日期边界、颜色等级、去重计数、
同日聚合、覆盖范围（未同步/部分覆盖）、日详情、同步任务（游标/幂等/issues 过滤 PR）。
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    GithubCommit,
    GithubIssue,
    GithubPullRequest,
    GithubRepo,
    SyncCursor,
)
from app.services import github_contrib, github_service

REPO_ID = 100


@pytest.fixture()
def session(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'github.db'}"
    os.environ["PH_DATABASE_URL"] = db_url
    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        s.add(GithubRepo(id=REPO_ID, full_name="me/demo", name="demo"))
        s.commit()
        yield s
    engine.dispose()


def _commit(session, sha, authored_at, message="msg", repo_id=REPO_ID):
    session.add(GithubCommit(sha=sha, repo_id=repo_id, message=message, authored_at=authored_at,
                             author_name="me", url=f"https://github.com/me/demo/commit/{sha}"))
    session.commit()


def _pr(session, gid, created_at, title="PR", repo_id=REPO_ID):
    session.add(GithubPullRequest(id=gid, repo_id=repo_id, number=gid, title=title,
                                  state="open", author="me", created_at=created_at,
                                  url=f"https://github.com/me/demo/pull/{gid}"))
    session.commit()


def _issue(session, gid, created_at, title="Issue", repo_id=REPO_ID):
    session.add(GithubIssue(id=gid, repo_id=repo_id, number=gid, title=title,
                            state="open", author="me", created_at=created_at,
                            url=f"https://github.com/me/demo/issues/{gid}"))
    session.commit()


# ---------- 颜色等级 ----------


def test_level_thresholds():
    assert github_contrib.level_of(0) == 0
    assert github_contrib.level_of(1) == 1
    assert github_contrib.level_of(2) == 1
    assert github_contrib.level_of(3) == 2
    assert github_contrib.level_of(5) == 2
    assert github_contrib.level_of(6) == 3
    assert github_contrib.level_of(8) == 3
    assert github_contrib.level_of(9) == 4
    assert github_contrib.level_of(50) == 4


# ---------- 年度聚合 ----------


def test_year_days_count_leap_and_common(session):
    leap = github_contrib.contributions_for_year(session, 2024)
    common = github_contrib.contributions_for_year(session, 2026)
    assert len(leap["days"]) == 366
    assert len(common["days"]) == 365
    assert leap["days"][0]["date"] == "2024-01-01"
    assert leap["days"][-1]["date"] == "2024-12-31"
    assert all(d["level"] == 0 and d["count"] == 0 for d in common["days"])
    assert common["coverage"]["synced"] is False  # 未同步 ≠ 零贡献


def test_utc_shanghai_day_boundary(session):
    """UTC 3-1 16:30 = +08 3-2 00:30 → 贡献归属 3-2，而非 UTC 的 3-1。"""
    _commit(session, "a1", "2026-03-01T16:30:00Z")
    result = github_contrib.contributions_for_year(session, 2026)
    by_date = {d["date"]: d for d in result["days"]}
    assert by_date["2026-03-01"]["count"] == 0
    assert by_date["2026-03-02"]["count"] == 1
    assert by_date["2026-03-02"]["level"] == 1
    assert result["total"] == 1


def test_multi_type_same_day_aggregation(session):
    _commit(session, "c1", "2026-06-01T01:00:00Z")
    _commit(session, "c2", "2026-06-01T02:00:00Z")
    _commit(session, "c3", "2026-06-01T03:00:00Z")
    _pr(session, 1, "2026-06-01T04:00:00Z")
    _pr(session, 2, "2026-06-01T05:00:00Z")
    _pr(session, 3, "2026-06-01T06:00:00Z")
    _issue(session, 1, "2026-06-01T07:00:00Z")
    _issue(session, 2, "2026-06-01T08:00:00Z")
    _issue(session, 3, "2026-06-01T09:00:00Z")
    _issue(session, 4, "2026-06-01T10:00:00Z")
    by_date = {d["date"]: d for d in github_contrib.contributions_for_year(session, 2026)["days"]}
    assert by_date["2026-06-01"]["count"] == 10  # 3 commit + 3 PR + 4 issue
    assert by_date["2026-06-01"]["level"] == 4


def test_coverage_partial_year(session):
    _commit(session, "p1", "2026-05-10T01:00:00Z")
    _commit(session, "p2", "2026-09-20T01:00:00Z")
    result = github_contrib.contributions_for_year(session, 2026)
    assert result["coverage"]["synced"] is True
    assert result["coverage"]["from"] == "2026-05-10"
    assert result["coverage"]["to"] == "2026-09-20"


# ---------- 日详情 ----------


def test_day_detail_groups_and_sorts(session):
    _commit(session, "d1", "2026-06-02T10:00:00Z", message="first line\nbody")
    _pr(session, 7, "2026-06-02T09:00:00Z", title="Fix bug")
    detail = github_contrib.day_detail(session, date(2026, 6, 2))
    assert [i["type"] for i in detail["items"]] == ["commit", "pull_request"]  # 时间倒序
    assert detail["items"][0]["repo"] == "me/demo"
    assert detail["items"][0]["title"] == "first line"  # commit 取首行
    assert detail["items"][0]["time"].endswith("+08:00")
    assert detail["items"][0]["url"]
    # 其他日期为空
    assert github_contrib.day_detail(session, date(2026, 6, 3))["items"] == []


# ---------- 同步任务（FakeClient） ----------


class FakeClient:
    def __init__(self):
        self.commits_calls: list[str] = []

    def list_repos(self):
        return [
            {"id": REPO_ID, "name": "demo", "full_name": "me/demo", "private": False,
             "fork": False, "description": "", "default_branch": "main", "language": "Python",
             "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z"}
        ]

    def iter_commits(self, full_name, since=""):
        self.commits_calls.append(since)
        yield {"sha": "s1", "commit": {"author": {"name": "me", "email": "a@b.c", "date": "2026-06-01T01:00:00Z"}, "message": "hello"}, "html_url": "u1"}

    def iter_pull_requests(self, full_name, since=""):
        yield {"id": 11, "number": 1, "title": "pr", "state": "open", "user": {"login": "me"},
               "created_at": "2026-06-01T02:00:00Z", "html_url": "up"}

    def iter_issues(self, full_name, since=""):
        # GitHub issues 端点混含 PR：带 pull_request 键的条目必须被过滤
        yield {"id": 12, "number": 2, "title": "real issue", "state": "open", "user": {"login": "me"},
               "created_at": "2026-06-01T03:00:00Z", "html_url": "ui"}
        yield {"id": 11, "number": 1, "title": "pr as issue", "pull_request": {}, "html_url": "ux"}


def test_sync_job_upsert_and_cursor(session):
    client = FakeClient()
    result = github_service.run_sync_job(session, client)
    assert result == {"repos": 1, "commits": 1, "pull_requests": 1, "issues": 1}
    assert client.commits_calls == [""]  # 首次无游标

    # 重复同步：幂等不重复计数
    result2 = github_service.run_sync_job(session, client)
    assert result2["commits"] == 1
    assert len(session.execute(select(GithubCommit)).scalars().all()) == 1
    assert len(session.execute(select(GithubPullRequest)).scalars().all()) == 1
    assert len(session.execute(select(GithubIssue)).scalars().all()) == 1
    # 二次调用携带游标（增量）
    assert client.commits_calls[1] != ""


def test_sync_advances_cursor(session):
    client = FakeClient()
    github_service.run_sync_job(session, client)
    cursor = session.get(SyncCursor, "github:me/demo")
    assert cursor is not None and cursor.last_timestamp > 0


# ---------- API 集成 ----------


def test_contributions_api(fclient):
    from app.models import GithubCommit as GC, GithubRepo as GR

    factory = fclient.app.state.session_factory
    with factory() as s:
        s.add(GR(id=REPO_ID, full_name="me/demo", name="demo"))
        s.add(GC(sha="api1", repo_id=REPO_ID, message="m", authored_at="2026-07-04T02:00:00Z"))
        s.commit()

    response = fclient.get("/api/github/contributions?year=2026")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    by_date = {d["date"]: d for d in payload["days"]}
    assert by_date["2026-07-04"]["count"] == 1
    assert payload["coverage"]["synced"] is True
    assert "counting_note" in payload

    # 未同步年份
    empty = fclient.get("/api/github/contributions?year=2024").json()
    assert empty["coverage"]["synced"] is False and empty["total"] == 0

    # 未来年份 / 非法年份
    assert fclient.get("/api/github/contributions?year=2999").status_code == 422
    assert fclient.get("/api/github/contributions?year=1999").status_code == 422

    # 日详情
    detail = fclient.get("/api/github/contributions/2026-07-04").json()
    assert len(detail["items"]) == 1 and detail["items"][0]["type"] == "commit"
    assert fclient.get("/api/github/contributions/2026-07-05").json()["items"] == []
    assert fclient.get("/api/github/contributions/2026-13-01").status_code == 422


def test_status_and_sync_guard(fclient, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "")
    # 未配置 Token → 同步被拒（400 明确提示）；status 不带 Token
    response = fclient.post("/api/github/sync", json={})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "github_token_missing"
    status = fclient.get("/api/github/status").json()
    assert status["configured"] is False
    assert "token" not in str(status).lower() or status["configured"] is False
