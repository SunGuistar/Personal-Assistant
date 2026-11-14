"""persistent daily question rounds

Revision ID: ff33ecde0a9e
Revises: 8d660ffab446
Create Date: 2026-11-14 12:28:26.017179

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff33ecde0a9e'
down_revision: Union[str, Sequence[str], None] = '8d660ffab446'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "daily_question_rounds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_date", sa.String(10), nullable=False, unique=True),
        sa.Column("queue_json", sa.Text(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("daily_question_rounds")
