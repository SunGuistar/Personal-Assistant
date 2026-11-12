"""book_url

阅读管理：books 增加 url 列（书籍/文章/视频链接，可空，默认 ''）。
链接仅作为记录与跳转入口，具体内容不在列表/卡片展示栏渲染。

Revision ID: cfdb6fd27f78
Revises: 438bace3d114
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cfdb6fd27f78'
down_revision: Union[str, Sequence[str], None] = '438bace3d114'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("url", sa.String(1024), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("books") as batch:
        batch.drop_column("url")
