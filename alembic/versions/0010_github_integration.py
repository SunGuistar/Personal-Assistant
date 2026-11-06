"""阶段一迁移：GitHub 数据集成四张表（repos / commits / pull_requests / issues）。

- 时间字段存 GitHub 侧 ISO8601 UTC 文本（带 Z），展示时由服务层转 Asia/Shanghai。
- commits 以 sha 为主键、PR/Issue 以 GitHub id 为主键，upsert 幂等，重复同步不重复计数。
- 贡献统计口径（Personal Hub 口径，非 GitHub 官方）：某天贡献数 = 当天（+08:00）
  作者提交的 commit 数 + 当天创建的 PR 数 + 当天创建的 Issue 数；详见 github_contrib 模块。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_repos",
        sa.Column("id", sa.Integer(), primary_key=True),  # GitHub 仓库 id
        sa.Column("name", sa.String(128), nullable=False, server_default=""),
        sa.Column("full_name", sa.String(255), nullable=False, unique=True),
        sa.Column("private", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fork", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_branch", sa.String(128), nullable=False, server_default=""),
        sa.Column("language", sa.String(64), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("synced_at", sa.String(32), nullable=False, server_default=""),
    )
    op.create_table(
        "github_commits",
        sa.Column("sha", sa.String(64), primary_key=True),
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("author_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("author_email", sa.String(128), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("authored_at", sa.String(32), nullable=False, server_default=""),  # UTC ISO
        sa.Column("url", sa.String(255), nullable=False, server_default=""),
    )
    op.create_index("ix_github_commits_repo", "github_commits", ["repo_id"])
    op.create_table(
        "github_pull_requests",
        sa.Column("id", sa.Integer(), primary_key=True),  # GitHub PR id
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("state", sa.String(16), nullable=False, server_default=""),
        sa.Column("author", sa.String(128), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("closed_at", sa.String(32), nullable=True),
        sa.Column("merged_at", sa.String(32), nullable=True),
        sa.Column("url", sa.String(255), nullable=False, server_default=""),
    )
    op.create_index("ix_github_pull_requests_repo", "github_pull_requests", ["repo_id"])
    op.create_table(
        "github_issues",
        sa.Column("id", sa.Integer(), primary_key=True),  # GitHub Issue id
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("state", sa.String(16), nullable=False, server_default=""),
        sa.Column("author", sa.String(128), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("closed_at", sa.String(32), nullable=True),
        sa.Column("url", sa.String(255), nullable=False, server_default=""),
    )
    op.create_index("ix_github_issues_repo", "github_issues", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_github_issues_repo", table_name="github_issues")
    op.drop_table("github_issues")
    op.drop_index("ix_github_pull_requests_repo", table_name="github_pull_requests")
    op.drop_table("github_pull_requests")
    op.drop_index("ix_github_commits_repo", table_name="github_commits")
    op.drop_table("github_commits")
    op.drop_table("github_repos")
