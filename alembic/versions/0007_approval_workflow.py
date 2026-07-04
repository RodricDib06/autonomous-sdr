"""Human-in-the-loop approval workflow for outreach emails.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-03
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outreach_emails", sa.Column("approved_by_id", sa.String(36),
                                               sa.ForeignKey("users.id"), nullable=True))
    op.add_column("outreach_emails", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("outreach_emails", sa.Column("rejection_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("outreach_emails", "rejection_reason")
    op.drop_column("outreach_emails", "approved_at")
    op.drop_column("outreach_emails", "approved_by_id")
