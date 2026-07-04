"""Recipient timezone on leads for local-time send windows.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-03
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("timezone", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "timezone")
