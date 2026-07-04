#!/usr/bin/env python
"""
Database initialization script.
Creates all tables and optionally seeds sample data.
"""
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path so app imports work when running as a script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.connection import create_all_tables, engine
from app.database import models
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def init_db():
    """Initialize database tables"""
    try:
        log.info("Creating database tables...")
        create_all_tables()
        log.info("✓ Database tables created successfully")
    except Exception as e:
        log.error(f"✗ Failed to create database tables: {e}")
        raise


def verify_db():
    """Verify database is working"""
    try:
        log.info("Verifying database connection...")
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        # Test basic query
        lead_count = db.query(models.Lead).count()
        log.info(f"✓ Database verified (currently {lead_count} leads)")
        
        db.close()
        return True
    except Exception as e:
        log.error(f"✗ Database verification failed: {e}")
        return False


if __name__ == "__main__":
    log.info("========== AutonomousSDR Database Init ==========")
    init_db()
    if verify_db():
        log.info("✓ Database is ready")
    else:
        log.error("✗ Database verification failed")
        exit(1)
