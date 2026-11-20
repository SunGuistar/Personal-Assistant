"""add_experiences

Revision ID: 64480c6d545b
Revises: ff33ecde0a9e
Create Date: 2026-11-15 12:29:34.354771

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64480c6d545b'
down_revision: Union[str, Sequence[str], None] = 'ff33ecde0a9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'experiences',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('problem', sa.Text(), nullable=False),
        sa.Column('solution', sa.Text(), nullable=False),
        sa.Column('tags', sa.String(200), nullable=False, server_default=''),
        sa.Column('created_at', sa.String(32), nullable=False),
        sa.Column('updated_at', sa.String(32), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('experiences')
