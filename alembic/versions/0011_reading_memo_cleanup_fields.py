"""2026-11 第四轮优化迁移（SQLite，存量数据兼容）：

- books：新增 title_cn（标题中文翻译，可空串）与 book_type
  （book/article/video/essay，存量默认 book）；
- memos：新增 task_type（内部保存的计划类型，空串=未保存过；
  转每日任务时按此恢复，空则回退默认 daily），前端不展示；
- cleanup_reviews：新增 summary（每次审核生成候选时写入的审核说明文字）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("books") as batch:
        batch.add_column(
            sa.Column("title_cn", sa.String(200), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("book_type", sa.String(16), nullable=False, server_default="book")
        )

    with op.batch_alter_table("memos") as batch:
        batch.add_column(
            sa.Column("task_type", sa.String(16), nullable=False, server_default="")
        )

    with op.batch_alter_table("cleanup_reviews") as batch:
        batch.add_column(
            sa.Column("summary", sa.Text(), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("cleanup_reviews") as batch:
        batch.drop_column("summary")

    with op.batch_alter_table("memos") as batch:
        batch.drop_column("task_type")

    with op.batch_alter_table("books") as batch:
        batch.drop_column("book_type")
        batch.drop_column("title_cn")
