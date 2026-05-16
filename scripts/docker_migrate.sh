#!/bin/bash
# Run database migrations + seed demo data inside Docker.
# Called by the `migrate` init service in docker-compose.yml.
set -e

echo "=== AutonomousSDR: Running migrations ==="

# Alembic handles all schema creation / upgrades.
# On a brand-new database it creates every table.
# On an existing database it applies only pending migrations.
alembic upgrade head

# pgvector extension is optional — enables semantic search via embeddings.
# Fails gracefully; the app falls back to keyword search without it.
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null \
  || echo "  ⚠  pgvector extension not available — semantic search will use keyword fallback"

echo "=== Running demo data seeder ==="
python scripts/seed_demo_data.py

echo "=== Init complete ==="
