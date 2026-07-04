"""Compliance & deliverability: suppression list (do-not-contact).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-03
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suppression_list",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("value", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="email"),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=True),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("suppression_list")
