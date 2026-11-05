"""阶段 6+ 迁移：计划"重要"标记与排序、完成时间、资讯中文翻译缓存。

- long_term_plans：is_important（重要置顶）、sort_order（手动排序）、completed_at（标记完成时间，可空——历史完成时间未知不得伪造，展示"完成时间未知"）；
- daily_tasks：is_important、completed_at（标记完成时间，可空）；
- news_items：title_zh / summary_zh / translate_status（中文翻译缓存；''=未尝试，
  done=成功，failed=失败回退原文；已是中文的资讯直接回填原文不计翻译）；
- 存量数据：sort_order 为 0 的行按 id 回填，保持既有展示顺序不变；存量已完成
  计划的 completed_at 保持 NULL（不伪造完成时间），由历史视图展示"完成时间未知"。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("long_term_plans") as batch:
        batch.add_column(sa.Column("is_important", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("completed_at", sa.String(32), nullable=True))
    op.execute("UPDATE long_term_plans SET sort_order = id WHERE sort_order = 0")

    with op.batch_alter_table("daily_tasks") as batch:
        batch.add_column(sa.Column("is_important", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("completed_at", sa.String(32), nullable=True))
    op.execute("UPDATE daily_tasks SET sort_order = id WHERE sort_order = 0")

    with op.batch_alter_table("news_items") as batch:
        batch.add_column(sa.Column("title_zh", sa.String(512), nullable=False, server_default=""))
        batch.add_column(sa.Column("summary_zh", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("translate_status", sa.String(16), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("news_items") as batch:
        batch.drop_column("translate_status")
        batch.drop_column("summary_zh")
        batch.drop_column("title_zh")
    with op.batch_alter_table("daily_tasks") as batch:
        batch.drop_column("completed_at")
        batch.drop_column("is_important")
    with op.batch_alter_table("long_term_plans") as batch:
        batch.drop_column("completed_at")
        batch.drop_column("sort_order")
        batch.drop_column("is_important")
