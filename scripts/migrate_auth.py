#!/usr/bin/env python
"""
Migration: Phase 3 auth tables (users, api_keys).
Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import logging
from sqlalchemy import text
from app.database.connection import engine

# ─── DEPRECATED ──────────────────────────────────────────────────────────────
# This phase script predates the Alembic migration chain and is kept only for
# legacy installs (make migrate-legacy). New/current installs should use:
#     alembic upgrade head
# ─────────────────────────────────────────────────────────────────────────────
print("[DEPRECATED] Prefer 'alembic upgrade head' — this script is kept for legacy installs only.")


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS users (
        id          VARCHAR(36)  PRIMARY KEY,
        email       VARCHAR(255) NOT NULL UNIQUE,
        password_hash TEXT       NOT NULL,
        role        VARCHAR(20)  NOT NULL DEFAULT 'rep',
        is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
        last_login_at TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)",
    """CREATE TABLE IF NOT EXISTS api_keys (
        id           VARCHAR(36)  PRIMARY KEY,
        user_id      VARCHAR(36)  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name         VARCHAR(100) NOT NULL,
        key_prefix   VARCHAR(12)  NOT NULL,
        key_hash     VARCHAR(64)  NOT NULL UNIQUE,
        is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
        last_used_at TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS ix_api_keys_user_id  ON api_keys (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys (key_hash)",
]


def run():
    with engine.connect() as conn:
        for sql in MIGRATIONS:
            conn.execute(text(sql))
            first_line = sql.strip().splitlines()[0]
            log.info(f"✓ {first_line}")
        conn.commit()
    log.info("Auth migration complete.")


if __name__ == "__main__":
    run()
