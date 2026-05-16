"""Initial schema — full baseline for all AutonomousSDR tables.

This single migration replaces the previous collection of ad-hoc scripts
(init_db.py, migrate_auth.py, migrate_phase2_fields.py, etc.) with a
versioned Alembic migration.

For fresh deployments:
    alembic upgrade head          ← creates all tables

For existing deployments (tables already exist):
    alembic stamp head            ← marks DB as current without re-running

Revision ID: 0001
Revises:
Create Date: 2026-05-15
"""

from typing import Sequence, Union
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Delegate to SQLAlchemy's create_all so the migration stays in sync with
    # the ORM models automatically. Any future schema changes should use
    # op.add_column / op.create_table / etc. instead of modifying this file.
    from app.database.connection import Base
    import app.database.models  # noqa: F401 — registers all models

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from app.database.connection import Base
    import app.database.models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
