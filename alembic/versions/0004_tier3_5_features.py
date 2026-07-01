"""Tier 3-5 features: objection routing, sentiment gate, pre-call brief,
event sourcing, priority queue metrics, lookalike scoring, org chart traversal.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-01
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Lead: lookalike scoring + org-chart referral chain
    op.add_column("leads", sa.Column("lookalike_score", sa.Float(), nullable=True))
    op.add_column("leads", sa.Column("referred_by_lead_id", sa.String(36),
                                     sa.ForeignKey("leads.id"), nullable=True))

    # Conversation: sentiment classification + human handoff gate
    op.add_column("conversations", sa.Column("sentiment", sa.String(50), nullable=True))
    op.add_column("conversations", sa.Column("needs_human", sa.Boolean(),
                                              nullable=True, server_default="false"))
    op.add_column("conversations", sa.Column("human_flagged_at", sa.DateTime(), nullable=True))

    # BookingRequest: pre-call brief
    op.add_column("booking_requests", sa.Column("pre_call_brief", sa.Text(), nullable=True))

    # LeadEvent: append-only event sourcing log
    op.create_table(
        "lead_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=False, index=True),
        sa.Column("event_type", sa.String(100), nullable=False, index=True),
        sa.Column("agent_name", sa.String(100), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_lead_events_created_at", "lead_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("lead_events")
    op.drop_column("booking_requests", "pre_call_brief")
    op.drop_column("conversations", "human_flagged_at")
    op.drop_column("conversations", "needs_human")
    op.drop_column("conversations", "sentiment")
    op.drop_column("leads", "referred_by_lead_id")
    op.drop_column("leads", "lookalike_score")
