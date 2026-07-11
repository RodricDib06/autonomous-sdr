"""
Phase 4 migration: enable pgvector and add embedding column to conversations.

Run this ONCE after deploying Phase 4.
Safe to re-run — all statements use IF NOT EXISTS / IF EXISTS guards.

Prerequisites:
  - PostgreSQL 13+ with the pgvector extension available.
    On Supabase: already enabled.
    On local Postgres: run `CREATE EXTENSION IF NOT EXISTS vector;` as superuser.
    On Railway: add the pgvector plugin to your Postgres instance.

Usage:
  python scripts/migrate_phase4_pgvector.py

What it does:
  1. Enables the vector extension.
  2. Adds an `embedding vector(768)` column to the conversations table.
  3. Creates an HNSW index for fast cosine similarity search.

If this script fails with "could not open extension control file" it means
pgvector is not installed on your Postgres server. The app still works — it
just falls back to keyword search for semantic queries.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─── DEPRECATED ──────────────────────────────────────────────────────────────
# This phase script predates the Alembic migration chain and is kept only for
# legacy installs (make migrate-legacy). New/current installs should use:
#     alembic upgrade head
# ─────────────────────────────────────────────────────────────────────────────
print("[DEPRECATED] Prefer 'alembic upgrade head' — this script is kept for legacy installs only.")


from app.database.connection import engine
from sqlalchemy import text

STEPS = [
    (
        "Enable pgvector extension",
        "CREATE EXTENSION IF NOT EXISTS vector;",
    ),
    (
        "Add embedding column to conversations",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS embedding vector(768);",
    ),
    (
        "Create HNSW index for cosine similarity search",
        """
        CREATE INDEX IF NOT EXISTS conversations_embedding_hnsw
        ON conversations USING hnsw (embedding vector_cosine_ops);
        """,
    ),
]

if __name__ == "__main__":
    print("Phase 4 — pgvector migration")
    with engine.connect() as conn:
        for label, sql in STEPS:
            try:
                conn.execute(text(sql))
                conn.commit()
                print(f"  ✓ {label}")
            except Exception as e:
                print(f"  ✗ {label}: {e}")
                print("    → App will fall back to keyword search for semantic queries.")
    print("Done.")
