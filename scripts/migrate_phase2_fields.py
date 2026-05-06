#!/usr/bin/env python
"""
Migration: Phase 2 bulk operations fields.
Safe to run multiple times — uses ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import logging
from sqlalchemy import text
from app.database.connection import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MIGRATIONS = [
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS tags JSONB",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE",
    """CREATE TABLE IF NOT EXISTS import_history (
        id VARCHAR(36) PRIMARY KEY,
        filename VARCHAR(255) NOT NULL,
        started_at TIMESTAMP NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMP,
        total INTEGER DEFAULT 0,
        successful INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        duplicates INTEGER DEFAULT 0,
        imported_by VARCHAR(255)
    )""",
]


def run():
    with engine.connect() as conn:
        for sql in MIGRATIONS:
            conn.execute(text(sql))
            first_line = sql.strip().splitlines()[0]
            log.info(f"✓ {first_line}")
        conn.commit()
    log.info("Phase 2 migration complete.")


if __name__ == "__main__":
    run()
