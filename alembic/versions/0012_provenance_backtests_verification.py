"""Provenance-grounded emails, backtest mode, and email verification.

- outreach_emails.claims: JSONB grounding report (claims → research sources)
- leads.email_verification_*: deliverability status set by the pre-send
  verifier and by hard-bounce detection
- backtest_runs / backtest_records: historical CSV replays through the
  deterministic qualifier, predictions stored next to real outcomes

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-14
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outreach_emails", sa.Column("claims", JSONB(), nullable=True))

    op.add_column("leads", sa.Column("email_verification_status", sa.String(20), nullable=True))
    op.add_column("leads", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column("leads", sa.Column("email_verification_detail", JSONB(), nullable=True))

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="complete"),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "backtest_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("backtest_runs.id"), nullable=False, index=True),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("actual_outcome", sa.String(10), nullable=False),
        sa.Column("predicted_verdict", sa.String(10), nullable=False),
        sa.Column("predicted_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("icp_match", sa.Boolean(), nullable=True),
        sa.Column("features", JSONB(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("backtest_records")
    op.drop_table("backtest_runs")
    op.drop_column("leads", "email_verification_detail")
    op.drop_column("leads", "email_verified_at")
    op.drop_column("leads", "email_verification_status")
    op.drop_column("outreach_emails", "claims")
