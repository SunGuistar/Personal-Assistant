"""GitHub 数据集成模型（阶段一，迁移 0010）。

时间字段一律存 GitHub 侧 ISO8601 UTC 文本（如 2026-11-06T08:30:00Z），
展示与统计归属日由服务层统一转 Asia/Shanghai（见 github_contrib）。
主键取 GitHub 天然唯一标识（repo id / commit sha / PR id / Issue id），
同步 upsert 幂等，不重复计数。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class GithubRepo(Base):
    __tablename__ = "github_repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # GitHub 仓库 id
    name: Mapped[str] = mapped_column(String(128), default="")
    full_name: Mapped[str] = mapped_column(String(255), unique=True)
    private: Mapped[int] = mapped_column(Integer, default=0)
    fork: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    default_branch: Mapped[str] = mapped_column(String(128), default="")
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), default="")
    updated_at: Mapped[str] = mapped_column(String(32), default="")
    synced_at: Mapped[str] = mapped_column(String(32), default=_now)  # 本地最近同步时间


class GithubCommit(Base):
    __tablename__ = "github_commits"

    sha: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[int] = mapped_column(Integer, index=True)
    author_name: Mapped[str] = mapped_column(String(128), default="")
    author_email: Mapped[str] = mapped_column(String(128), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    authored_at: Mapped[str] = mapped_column(String(32), default="")  # UTC ISO
    url: Mapped[str] = mapped_column(String(255), default="")


class GithubPullRequest(Base):
    __tablename__ = "github_pull_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # GitHub PR id
    repo_id: Mapped[int] = mapped_column(Integer, index=True)
    number: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(512), default="")
    state: Mapped[str] = mapped_column(String(16), default="")
    author: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[str] = mapped_column(String(32), default="")
    closed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    merged_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    url: Mapped[str] = mapped_column(String(255), default="")


class GithubIssue(Base):
    __tablename__ = "github_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # GitHub Issue id
    repo_id: Mapped[int] = mapped_column(Integer, index=True)
    number: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(512), default="")
    state: Mapped[str] = mapped_column(String(16), default="")
    author: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[str] = mapped_column(String(32), default="")
    closed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    url: Mapped[str] = mapped_column(String(255), default="")
