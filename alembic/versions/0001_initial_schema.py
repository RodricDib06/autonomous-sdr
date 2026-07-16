"""Initial schema — frozen baseline for all AutonomousSDR tables.

This is the schema exactly as it stood BEFORE revision 0002. It is written
out explicitly (not generated from the live ORM metadata) so the migration
chain replays correctly on a fresh database: an earlier version of this file
delegated to Base.metadata.create_all(), which built tables from the
*current* models — so every column that 0002+ later adds already existed,
and `alembic upgrade head` failed on the first ALTER TABLE.

Policy: this file is FROZEN. Schema changes go in new revisions via
op.add_column / op.create_table — never here.

For fresh deployments:
    alembic upgrade head          ← replays the full chain

For pre-alembic deployments (tables already created by the app's startup
create_all):
    alembic stamp head            ← marks DB as current without re-running

Revision ID: 0001
Revises:
Create Date: 2026-05-15 (frozen 2026-07-16)
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "leads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("completeness_score", sa.Float(), nullable=True),
        sa.Column("data_quality_score", sa.Float(), nullable=True),
        sa.Column("quality_metadata", JSONB(), nullable=True),
        sa.Column("tags", JSONB(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("assigned_to_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("conversion_status", sa.String(50), nullable=False),
        sa.Column("conversion_updated_at", sa.DateTime(), nullable=True),
        sa.Column("conversion_notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "enrichments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=False, index=True),
        sa.Column("job_title", sa.String(255), nullable=True),
        sa.Column("seniority", sa.String(100), nullable=True),
        sa.Column("company_size", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("revenue_estimate", sa.String(100), nullable=True),
        sa.Column("tech_stack", JSONB(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("enrichment_source", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "verdicts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=False, index=True),
        sa.Column("enrichment_id", sa.String(36), sa.ForeignKey("enrichments.id"), nullable=True),
        sa.Column("analysis_verdict", sa.String(50), nullable=True),
        sa.Column("analysis_reasoning", sa.Text(), nullable=True),
        sa.Column("bant_scores", JSONB(), nullable=True),
        sa.Column("icp_match", sa.Boolean(), nullable=True),
        sa.Column("validated", sa.Boolean(), nullable=True),
        sa.Column("final_verdict", sa.String(50), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("consistency_notes", sa.Text(), nullable=True),
        sa.Column("flags", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "agent_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=False, index=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("input_data", JSONB(), nullable=True),
        sa.Column("output_data", JSONB(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "import_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("successful", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("imported_by", sa.String(255), nullable=True),
    )

    op.create_table(
        "lead_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=False, index=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("old_value", sa.String(255), nullable=True),
        sa.Column("new_value", sa.String(255), nullable=True),
        sa.Column("changed_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "outreach_sequences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("steps", JSONB(), nullable=False),
        sa.Column("ab_variant", sa.String(10), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "outreach_emails",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=False, index=True),
        sa.Column("sequence_id", sa.String(36), sa.ForeignKey("outreach_sequences.id"), nullable=True),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("replied_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=False, index=True),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("messages", JSONB(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "booking_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("booking_link", sa.Text(), nullable=True),
        sa.Column("external_booking_id", sa.String(255), nullable=True),
        sa.Column("meeting_url", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "intent_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=False, index=True),
        sa.Column("signal_type", sa.String(100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("signal_metadata", JSONB(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "ab_test_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sequence_id", sa.String(36), sa.ForeignKey("outreach_sequences.id"), nullable=False, index=True),
        sa.Column("variant", sa.String(10), nullable=False),
        sa.Column("emails_sent", sa.Integer(), nullable=False),
        sa.Column("emails_opened", sa.Integer(), nullable=False),
        sa.Column("replies", sa.Integer(), nullable=False),
        sa.Column("meetings_booked", sa.Integer(), nullable=False),
        sa.Column("conversions", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "icp_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("industries", JSONB(), nullable=True),
        sa.Column("seniority_levels", JSONB(), nullable=True),
        sa.Column("excluded_industries", JSONB(), nullable=True),
        sa.Column("min_employees", sa.Integer(), nullable=True),
        sa.Column("max_employees", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "optimization_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("old_weights", JSONB(), nullable=False),
        sa.Column("new_weights", JSONB(), nullable=False),
        sa.Column("improvement_score", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # Reverse dependency order
    op.drop_table("optimization_runs")
    op.drop_table("icp_config")
    op.drop_table("ab_test_results")
    op.drop_table("intent_signals")
    op.drop_table("booking_requests")
    op.drop_table("conversations")
    op.drop_table("outreach_emails")
    op.drop_table("outreach_sequences")
    op.drop_table("lead_history")
    op.drop_table("import_history")
    op.drop_table("api_keys")
    op.drop_table("agent_logs")
    op.drop_table("verdicts")
    op.drop_table("enrichments")
    op.drop_table("leads")
    op.drop_table("users")
