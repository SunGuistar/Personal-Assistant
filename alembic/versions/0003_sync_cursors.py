"""阶段 3 迁移：微信同步游标表（hub.db）。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_cursors",
        sa.Column("scope", sa.String(128), primary_key=True),  # chat_id
        sa.Column("last_timestamp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_msg_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("sync_cursors")
