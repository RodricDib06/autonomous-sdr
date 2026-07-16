from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings


def _database_url() -> str:
    url = settings.DATABASE_URL
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Point it at a Postgres instance, e.g. "
            "postgresql://user:pass@host:5432/sdr_db. On Railway: add a "
            "Postgres service and set DATABASE_URL=${{Postgres.DATABASE_URL}} "
            "on this service. Locally: copy .env.example to .env."
        )
    # Heroku/Railway-style URLs may use the deprecated postgres:// scheme,
    # which SQLAlchemy 2.x no longer accepts
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


engine = create_engine(_database_url())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables():
    from app.database import models  # noqa: F401 — ensures models are registered
    Base.metadata.create_all(bind=engine)
