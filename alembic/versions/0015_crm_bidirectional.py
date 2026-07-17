"""Bidirectional CRM sync (HubSpot OAuth).

- crm_connections: one OAuth-connected portal per org, tokens encrypted
- crm_sync_log: append-only audit of every sync in either direction
- leads.hubspot_contact_id: captured on push, resolves inbound webhooks

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-17
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("hubspot_contact_id", sa.String(50), nullable=True))
    op.create_index("ix_leads_hubspot_contact_id", "leads", ["hubspot_contact_id"])

    op.create_table(
        "crm_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("provider", sa.String(30), nullable=False, server_default="hubspot"),
        sa.Column("portal_id", sa.String(50), nullable=True, index=True),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("connected_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("last_outbound_at", sa.DateTime(), nullable=True),
        sa.Column("last_inbound_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "crm_sync_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("provider", sa.String(30), nullable=False, server_default="hubspot"),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey("leads.id"), nullable=True, index=True),
        sa.Column("external_id", sa.String(50), nullable=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("crm_sync_log")
    op.drop_table("crm_connections")
    op.drop_index("ix_leads_hubspot_contact_id", table_name="leads")
    op.drop_column("leads", "hubspot_contact_id")
