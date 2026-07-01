"""Tier 1 AI features: email quality judge, debate verdict transcript,
Thompson sampling bandit state, and predictive decay scoring.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-31
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # OutreachEmail: LLM-as-judge quality scores
    op.add_column("outreach_emails", sa.Column("quality_score", sa.Float(), nullable=True))
    op.add_column("outreach_emails", sa.Column("quality_flags", JSONB(), nullable=True))
    op.add_column("outreach_emails", sa.Column("quality_reasoning", sa.Text(), nullable=True))

    # Verdict: full debate transcript from advocate/critic/synthesis agents
    op.add_column("verdicts", sa.Column("debate_transcript", JSONB(), nullable=True))

    # Lead: exponential decay scoring + re-engagement tracking
    op.add_column("leads", sa.Column("decay_score", sa.Float(), nullable=True))
    op.add_column("leads", sa.Column("last_decay_check_at", sa.DateTime(), nullable=True))
    op.add_column("leads", sa.Column("reengagement_count", sa.Integer(), nullable=True,
                                     server_default="0"))


def downgrade() -> None:
    op.drop_column("outreach_emails", "quality_score")
    op.drop_column("outreach_emails", "quality_flags")
    op.drop_column("outreach_emails", "quality_reasoning")
    op.drop_column("verdicts", "debate_transcript")
    op.drop_column("leads", "decay_score")
    op.drop_column("leads", "last_decay_check_at")
    op.drop_column("leads", "reengagement_count")
