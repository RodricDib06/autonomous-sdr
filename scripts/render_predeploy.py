"""
Pre-deploy step for Render (and any PaaS running one command before cutover).

Does what scripts/docker_migrate.sh does, minus the demo seeding, and without
shelling out to `psql` — the API image installs libpq for psycopg2 but not the
postgres client binaries, so the extension has to be created over SQLAlchemy.

Render aborts the deploy if this exits non-zero, so only genuinely fatal
problems are allowed to propagate: a failed migration is fatal, a missing
pgvector extension is not (semantic search falls back to keyword search).

    python scripts/render_predeploy.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    print("=== AutonomousSDR pre-deploy ===", flush=True)

    print("-> alembic upgrade head", flush=True)
    result = subprocess.run(["alembic", "upgrade", "head"])
    if result.returncode != 0:
        print("!! migration failed — aborting deploy", flush=True)
        return result.returncode

    # Optional: enables pgvector semantic search. Render Postgres supports the
    # extension; other hosts may not, and the app works either way.
    print("-> CREATE EXTENSION IF NOT EXISTS vector", flush=True)
    try:
        from sqlalchemy import create_engine, text

        from app.config import settings

        engine = create_engine(settings.DATABASE_URL)
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        print("   pgvector ready", flush=True)
    except Exception as e:
        print(f"   pgvector unavailable ({e}) — semantic search uses keyword fallback", flush=True)

    print("=== pre-deploy complete ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
