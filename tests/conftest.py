import pytest
from sqlalchemy import create_engine, TypeDecorator, JSON
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Use SQLite in-memory for tests
TEST_SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


# Patch the JSONB type before importing models
def patch_jsonb_for_sqlite():
    """Patch JSONB to work with SQLite"""
    import sqlalchemy.dialects.postgresql
    
    # Create a custom JSONB that works with SQLite
    original_jsonb = sqlalchemy.dialects.postgresql.JSONB
    
    class TestJSONB(TypeDecorator):
        impl = JSON
        cache_ok = True
    
    sqlalchemy.dialects.postgresql.JSONB = TestJSONB
    return original_jsonb


# Apply patch before importing base
original_jsonb = patch_jsonb_for_sqlite()

from app.database.connection import Base
import app.database.models  # noqa: F401 — register all ORM models with Base


@pytest.fixture
def test_engine():
    # StaticPool shares one in-memory connection across all sessions in the test,
    # so tables created by create_all are visible to every subsequent session.
    engine = create_engine(
        TEST_SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def test_db(test_engine):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestingSessionLocal()
    yield db
    db.close()


@pytest.fixture
def test_session_factory(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def client(test_session_factory):
    """HTTP test client with DB overridden to in-memory SQLite."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database.connection import get_db

    def override_get_db():
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)
