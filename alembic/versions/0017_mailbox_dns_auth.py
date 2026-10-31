"""Store the SPF/DKIM/DMARC check result on each sending mailbox.

The rotation pool skips mailboxes whose domain doesn't authenticate; the
result is cached here and re-checked daily.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-31
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sending_mailboxes", sa.Column("dns_auth", JSONB(), nullable=True))
    op.add_column("sending_mailboxes", sa.Column("dns_checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("sending_mailboxes", "dns_checked_at")
    op.drop_column("sending_mailboxes", "dns_auth")
