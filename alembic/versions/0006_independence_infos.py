"""2026-11 综合优化迁移：计划目标字段、书籍重要标记、重要信息表、移除计划-任务关联。

- long_term_plans：新增 goal（具体目标，可空文本）；
- books：新增 is_important（重要置顶，与计划/任务同规则：重要 > 默认排序）；
- important_infos：新表（右侧栏"重要信息"，长期保存，不参与清理）；
- daily_tasks：删除 plan_id 列及外键（经检查真实库 0 条关联，确认无数据影响；
  长期计划与每日任务自此完全独立）。

均为新增/删列操作，不动既有数据；daily_tasks 用 batch 模式重建表以删除外键列。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("long_term_plans") as batch:
        batch.add_column(sa.Column("goal", sa.Text(), nullable=True))  # 具体目标，未填写为 NULL

    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("is_important", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "important_infos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )

    # 删除 daily_tasks.plan_id 及外键（0 条历史关联，已核查）
    with op.batch_alter_table("daily_tasks") as batch:
        batch.drop_column("plan_id")


def downgrade() -> None:
    with op.batch_alter_table("daily_tasks") as batch:
        batch.add_column(sa.Column("plan_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_daily_tasks_plan_id",
            "long_term_plans",
            ["plan_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.drop_table("important_infos")
    with op.batch_alter_table("books") as batch:
        batch.drop_column("is_important")
    with op.batch_alter_table("long_term_plans") as batch:
        batch.drop_column("goal")
