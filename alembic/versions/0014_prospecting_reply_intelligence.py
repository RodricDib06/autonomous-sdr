"""Prospecting runs + reply classification.

- prospecting_runs: audit trail for agent-sourced leads (criteria, provider,
  rejection breakdown per quality gate, cost)
- conversations.classification: reply-intelligence output ({category,
  subtype, confidence, method, extracted})

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-16
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prospecting_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("campaign_id", sa.String(36), sa.ForeignKey("campaigns.id"), nullable=True, index=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("criteria", JSONB(), nullable=True),
        sa.Column("requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected", JSONB(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )

    op.add_column("conversations", sa.Column("classification", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "classification")
    op.drop_table("prospecting_runs")
