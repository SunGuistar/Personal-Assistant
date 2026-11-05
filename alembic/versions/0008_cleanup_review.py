"""阶段 5 迁移：每周数据清理与人工审核（D4）四张表。

- cleanup_reviews：审核周期（week_id=所在周日，唯一；status pending/dismissed/done/skipped）；
- cleanup_candidates：候选分组快照（按群+日期；三层数量、可删/保留 chunk 及原因、执行状态）；
- cleanup_delete_items：删除计划明细（candidate × layer / 单个 chunk；pending→validated→done/failed，断点续跑）；
- cleanup_audit：审计（只记元数据，不记聊天正文）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cleanup_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("week_id", sa.String(16), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("confirmed_at", sa.String(32), nullable=True),
        sa.Column("reviewed_at", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )
    op.create_table(
        "cleanup_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("chat_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("msg_date", sa.String(10), nullable=False),
        sa.Column("snapshot_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("normalized_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_delete_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_keep_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("keep_reasons", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("size_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "state",
            sa.String(20),
            nullable=False,
            server_default="pending",  # pending/validated/deleted/failed/failed_protected
        ),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )
    op.create_index("ix_cleanup_candidates_review", "cleanup_candidates", ["review_id"])
    op.create_table(
        "cleanup_delete_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),  # normalized / snapshot / chunk
        sa.Column("ref_id", sa.String(128), nullable=False, server_default=""),
        sa.Column(
            "state",
            sa.String(16),
            nullable=False,
            server_default="pending",  # pending/validated/done/failed
        ),
        sa.Column("detail", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )
    op.create_index("ix_cleanup_items_candidate", "cleanup_delete_items", ["candidate_id"])
    op.create_table(
        "cleanup_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(32), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("cleanup_audit")
    op.drop_index("ix_cleanup_items_candidate", table_name="cleanup_delete_items")
    op.drop_table("cleanup_delete_items")
    op.drop_index("ix_cleanup_candidates_review", table_name="cleanup_candidates")
    op.drop_table("cleanup_candidates")
    op.drop_table("cleanup_reviews")
