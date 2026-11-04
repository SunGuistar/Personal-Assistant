"""阶段 4 迁移：技术资讯中心两张表（PRD §2.2 / ARCH §3.2）。

历史迁移，禁止修改/删除。2026-11 产品调整：资讯改为外部导航，
自建抓取下线；表与数据保留（保守策略，见 DEVELOPMENT_PLAN 阶段 4），
本文件仅作历史记录，不再用于新写入。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("endpoint", sa.String(512), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
        sa.UniqueConstraint("name", name="uq_news_sources_name"),
    )
    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("topic", sa.String(32), nullable=False, server_default="other"),
        sa.Column("published_at", sa.String(40), nullable=False),
        sa.Column("raw_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("heat_raw", sa.Float(), nullable=False, server_default="0"),
        sa.Column("norm_heat", sa.Float(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_favorite", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("fetched_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
        sa.UniqueConstraint("url", name="uq_news_items_url"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["news_sources.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_news_items_title_hash", "news_items", ["title_hash"])
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])
    op.create_index("ix_news_items_topic", "news_items", ["topic"])


def downgrade() -> None:
    op.drop_index("ix_news_items_topic", table_name="news_items")
    op.drop_index("ix_news_items_published_at", table_name="news_items")
    op.drop_index("ix_news_items_title_hash", table_name="news_items")
    op.drop_table("news_items")
    op.drop_table("news_sources")
