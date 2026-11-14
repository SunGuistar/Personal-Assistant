"""question feedback counts

Revision ID: 8d660ffab446
Revises: 222989684fbc
Create Date: 2026-11-14 12:15:06.947574

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d660ffab446'
down_revision: Union[str, Sequence[str], None] = '222989684fbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("daily_questions", sa.Column("remembered_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("daily_questions", sa.Column("forgotten_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("daily_questions", "forgotten_count")
    op.drop_column("daily_questions", "remembered_count")
