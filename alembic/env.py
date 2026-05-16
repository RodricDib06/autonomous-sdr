"""Alembic environment — wires the app's SQLAlchemy models into migration runs.

DATABASE_URL is read from app.config.settings so that the same env var used
by the application is also used for migrations. Set it before running any
alembic command:

    export DATABASE_URL=postgresql://user:pass@host/db
    alembic upgrade head

Or via .env file (pydantic-settings loads it automatically).
"""

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Register all ORM models so autogenerate can compare against them
from app.database.connection import Base  # noqa: E402
import app.database.models  # noqa: E402, F401

target_metadata = Base.metadata


def _get_url() -> str:
    from app.config import settings
    url = settings.DATABASE_URL
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Export it or add it to your .env file before running alembic."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL to stdout)."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,        # detect column type changes
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
