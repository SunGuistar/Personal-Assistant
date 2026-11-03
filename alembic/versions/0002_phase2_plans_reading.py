"""阶段 2 迁移：计划管理与阅读管理四张表（PRD §2.3/§2.4）。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "long_term_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="in_progress"),
        sa.Column("target_date", sa.String(10), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )

    op.create_table(
        "daily_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("long_term_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("task_date", sa.String(10), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("moved_from_date", sa.String(10), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )
    op.create_index("ix_daily_tasks_task_date", "daily_tasks", ["task_date"])

    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("author", sa.String(128), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="todo"),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(32), nullable=False, server_default=""),
    )

    op.create_table(
        "book_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "book_id",
            sa.Integer(),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(32), nullable=False, server_default=""),
    )
    op.create_index("ix_book_notes_book_id", "book_notes", ["book_id"])


def downgrade() -> None:
    op.drop_index("ix_book_notes_book_id", table_name="book_notes")
    op.drop_table("book_notes")
    op.drop_table("books")
    op.drop_index("ix_daily_tasks_task_date", table_name="daily_tasks")
    op.drop_table("daily_tasks")
    op.drop_table("long_term_plans")
