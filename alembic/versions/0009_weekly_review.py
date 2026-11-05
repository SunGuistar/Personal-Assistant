"""阶段一迁移：每周回顾 Agent 三张表。

- weekly_reviews：回顾草稿/正式周报（draft → confirmed，单向；
  week_start 部分唯一索引保证同一自然周仅一份正式周报，不可覆盖）。
- weekly_review_messages：回顾对话（多轮上下文持久化，刷新可恢复）。
- weekly_review_suggestions：下周建议（pending → accepted/modified/rejected；
  basis_json 存结构化依据，空数组 = 一般性建议）。

周报长期保留，不参与清理审核（清理只覆盖微信两库）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("week_start", sa.String(10), nullable=False),
        sa.Column("week_end", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("stats_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("analysis_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("user_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("report_md", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )
    op.create_index(
        "ux_weekly_reviews_confirmed_week",
        "weekly_reviews",
        ["week_start"],
        unique=True,
        sqlite_where=sa.text("status = 'confirmed'"),
    )
    op.create_table(
        "weekly_review_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
    )
    op.create_index("ix_weekly_review_messages_review", "weekly_review_messages", ["review_id"])
    op.create_table(
        "weekly_review_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("basis_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("final_content", sa.Text(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolved_at", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )
    op.create_index("ix_weekly_review_suggestions_review", "weekly_review_suggestions", ["review_id"])


def downgrade() -> None:
    op.drop_index("ix_weekly_review_suggestions_review", table_name="weekly_review_suggestions")
    op.drop_table("weekly_review_suggestions")
    op.drop_index("ix_weekly_review_messages_review", table_name="weekly_review_messages")
    op.drop_table("weekly_review_messages")
    op.drop_index("ux_weekly_reviews_confirmed_week", table_name="weekly_reviews")
    op.drop_table("weekly_reviews")
