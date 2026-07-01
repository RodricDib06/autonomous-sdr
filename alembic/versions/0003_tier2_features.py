"""Tier 2 real-time intelligence: trigger monitoring, IP de-anonymization,
job change detection.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-01
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Lead: trigger monitoring state + IP de-anonymization flag
    op.add_column("leads", sa.Column("last_trigger_checked_at", sa.DateTime(), nullable=True))
    op.add_column("leads", sa.Column("identified_via_ip", sa.Boolean(),
                                     nullable=True, server_default="false"))


def downgrade() -> None:
    op.drop_column("leads", "last_trigger_checked_at")
    op.drop_column("leads", "identified_via_ip")
