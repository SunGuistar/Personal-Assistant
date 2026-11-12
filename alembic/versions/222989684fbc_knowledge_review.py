"""knowledge_review

Revision ID: 222989684fbc
Revises: cfdb6fd27f78
Create Date: 2026-11-12 15:25:16.484328

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '222989684fbc'
down_revision: Union[str, Sequence[str], None] = 'cfdb6fd27f78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("daily_questions", sa.Column("tags", sa.String(200), nullable=False, server_default=""))
    op.add_column("daily_questions", sa.Column("review_level", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("daily_questions", sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("daily_questions", sa.Column("due_at", sa.String(32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for name in ("due_at", "review_count", "review_level", "tags"):
        op.drop_column("daily_questions", name)
