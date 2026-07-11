"""
Integration test fixtures — real Postgres + Redis, no JSONB patching.

These run in a separate pytest invocation from tests/ (whose conftest
replaces JSONB with a SQLite-compatible shim at import time). Requires
DATABASE_URL and REDIS_URL pointing at live services, with migrations
already applied (alembic upgrade head).
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "")
    return url if url.startswith("postgresql") else None


@pytest.fixture(scope="session")
def pg_engine():
    url = _database_url()
    if url is None:
        pytest.skip("DATABASE_URL is not a postgres URL — postgres integration tests skipped")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_db(pg_engine):
    """Session wrapped in an outer transaction that always rolls back."""
    connection = pg_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    db = Session()
    yield db
    db.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def pg_raw(pg_engine):
    with pg_engine.connect() as conn:
        yield conn


@pytest.fixture
def redis_client():
    import redis as redis_lib
    client = redis_lib.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis not reachable")
    yield client


def exec_scalar(conn, sql: str):
    return conn.execute(text(sql)).scalar()
