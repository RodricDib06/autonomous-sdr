"""Org-scope CSV import history.

import_history predates multi-tenancy and was missed by 0006, so every org
saw every other org's import filenames and counts. Existing rows backfill to
the default organization, matching how 0006 adopted pre-tenancy data.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-30
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "import_history",
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True),
    )
    op.create_index("ix_import_history_org_id", "import_history", ["org_id"])
    op.execute(
        "UPDATE import_history SET org_id = "
        "(SELECT id FROM organizations WHERE slug = 'default') WHERE org_id IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_import_history_org_id", table_name="import_history")
    op.drop_column("import_history", "org_id")
