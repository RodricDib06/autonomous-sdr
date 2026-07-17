"""Campaigns — goal-directed autonomy (campaign manager agent).

- campaigns: a quota + constraints handed to the agent
- campaign_plans: each observe→diagnose→propose cycle, with the metrics
  snapshot it was based on (auditability) and the periodic report
- campaign_action_log: append-only record of executed actions

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-16
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("goal_type", sa.String(30), nullable=False, server_default="meetings"),
        sa.Column("goal_target", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("constraints", JSONB(), nullable=True),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "campaign_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), sa.ForeignKey("campaigns.id"), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_approval"),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("diagnosis", sa.Text(), nullable=True),
        sa.Column("actions", JSONB(), nullable=True),
        sa.Column("metrics_snapshot", JSONB(), nullable=True),
        sa.Column("report_md", sa.Text(), nullable=True),
        sa.Column("approved_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "campaign_action_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("campaign_plans.id"), nullable=False, index=True),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("campaign_action_log")
    op.drop_table("campaign_plans")
    op.drop_table("campaigns")
