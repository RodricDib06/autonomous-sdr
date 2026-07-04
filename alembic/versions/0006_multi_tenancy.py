"""Multi-tenancy: organizations table + org_id on core entities.

Creates the default organization and backfills all existing rows onto it,
so single-tenant installs upgrade transparently.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-03
"""

import uuid
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ORG_ID = str(uuid.uuid4())

_ORG_SCOPED_TABLES = ["users", "leads", "outreach_sequences", "suppression_list", "icp_config"]


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("settings", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.execute(
        sa.text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, 'Default Organization', 'default', NOW())"
        ).bindparams(id=DEFAULT_ORG_ID)
    )

    for table in _ORG_SCOPED_TABLES:
        op.add_column(
            table,
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True),
        )
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])
        op.execute(
            sa.text(f"UPDATE {table} SET org_id = :id WHERE org_id IS NULL")  # noqa: S608
            .bindparams(id=DEFAULT_ORG_ID)
        )

    # Two orgs may suppress the same address — uniqueness moves to (org, value)
    op.drop_constraint("suppression_list_value_key", "suppression_list", type_="unique")
    op.create_index(
        "uq_suppression_org_value", "suppression_list", ["org_id", "value"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_suppression_org_value", table_name="suppression_list")
    op.create_unique_constraint("suppression_list_value_key", "suppression_list", ["value"])
    for table in reversed(_ORG_SCOPED_TABLES):
        op.drop_index(f"ix_{table}_org_id", table_name=table)
        op.drop_column(table, "org_id")
    op.drop_table("organizations")
