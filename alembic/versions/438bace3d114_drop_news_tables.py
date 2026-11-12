"""drop_news_tables

技术资讯功能整体下线：删除 news_sources / news_items 两张资讯缓存表。
downgrade 按 0004 + 0005 迁移后的最终结构重建（不含数据）。

Revision ID: 438bace3d114
Revises: 4e7f434df7dd
Create Date: 2026-11-12 12:08:36.451050

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '438bace3d114'
down_revision: Union[str, Sequence[str], None] = '4e7f434df7dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_news_items_topic", table_name="news_items")
    op.drop_index("ix_news_items_published_at", table_name="news_items")
    op.drop_index("ix_news_items_title_hash", table_name="news_items")
    op.drop_table("news_items")
    op.drop_table("news_sources")


def downgrade() -> None:
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
        sa.Column("title_zh", sa.String(512), nullable=False, server_default=""),
        sa.Column("summary_zh", sa.Text(), nullable=False, server_default=""),
        sa.Column("translate_status", sa.String(16), nullable=False, server_default=""),
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
