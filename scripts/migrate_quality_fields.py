#!/usr/bin/env python
"""
Migration: add data quality fields to leads table.
Safe to run multiple times — uses ADD COLUMN IF NOT EXISTS.
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
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS completeness_score FLOAT",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS data_quality_score FLOAT",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS quality_metadata JSONB",
]


def run():
    with engine.connect() as conn:
        for sql in MIGRATIONS:
            conn.execute(text(sql))
            log.info(f"✓ {sql}")
        conn.commit()
    log.info("Migration complete.")


if __name__ == "__main__":
    run()
