#!/usr/bin/env python
"""
Migration: Phase 5 sales enablement fields (lead assignment + conversion tracking).
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
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS assigned_to_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS conversion_status VARCHAR(50) DEFAULT 'unqualified'",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS conversion_updated_at TIMESTAMP",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS conversion_notes TEXT",
    """CREATE TABLE IF NOT EXISTS lead_history (
        id VARCHAR(36) PRIMARY KEY,
        lead_id VARCHAR(36) NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        event_type VARCHAR(50) NOT NULL,
        old_value VARCHAR(255),
        new_value VARCHAR(255),
        changed_by_id VARCHAR(36) REFERENCES users(id),
        changed_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_lead_history_lead_id ON lead_history(lead_id)",
    "CREATE INDEX IF NOT EXISTS idx_lead_history_changed_at ON lead_history(changed_at)",
]


def run():
    with engine.connect() as conn:
        for sql in MIGRATIONS:
            conn.execute(text(sql))
            first_line = sql.strip().splitlines()[0]
            log.info(f"✓ {first_line}")
        conn.commit()
    log.info("Phase 5 migration complete.")


if __name__ == "__main__":
    run()
