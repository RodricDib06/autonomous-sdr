#!/bin/bash
# Run all migrations + seed demo data inside Docker.
# Called by the `migrate` init service in docker-compose.yml.
set -e

echo "=== AutonomousSDR: Running migrations ==="

python scripts/init_db.py
python scripts/migrate_auth.py
python scripts/migrate_phase2_fields.py
python scripts/migrate_phase3_tables.py
python scripts/migrate_phase4_pgvector.py || echo "  ⚠  pgvector not installed — skipping (app falls back to keyword search)"
python scripts/migrate_phase5_fields.py   || echo "  ⚠  migrate_phase5_fields skipped"

echo "=== Running demo data seeder ==="
python scripts/seed_demo_data.py

echo "=== Init complete ==="
