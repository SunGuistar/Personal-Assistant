"""2026-11 第三轮优化迁移：每日任务类型/内容字段 + 随手备忘表（SQLite）。

- daily_tasks：新增 task_type（固定枚举 daily/feature_add/feature_optimize/idea，
  存量数据默认 daily）与 content（可选任务内容/备注，供随手备忘转换承载文本）；
- memos：新表（随手备忘，多条结构化记录，与 important_infos 同规范但独立概念）；
- 重要信息表（important_infos）不变。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TASK_TYPE_DAILY = "daily"


def upgrade() -> None:
    with op.batch_alter_table("daily_tasks") as batch:
        batch.add_column(
            sa.Column("task_type", sa.String(16), nullable=False, server_default=TASK_TYPE_DAILY)
        )
        batch.add_column(sa.Column("content", sa.Text(), nullable=True))

    op.create_table(
        "memos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("memos")
    with op.batch_alter_table("daily_tasks") as batch:
        batch.drop_column("content")
        batch.drop_column("task_type")
