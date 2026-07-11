"""
Phase 3 migration: create all new tables added in this phase.

New tables:
  - outreach_sequences
  - outreach_emails
  - conversations
  - booking_requests
  - intent_signals
  - ab_test_results
  - optimization_runs

Usage:
  python scripts/migrate_phase3_tables.py
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


from app.database.connection import Base, engine
from app.database.models import (  # noqa: F401 — import to register with metadata
    OutreachSequence, OutreachEmail, Conversation,
    BookingRequest, IntentSignal, ABTestResult, OptimizationRun,
)

if __name__ == "__main__":
    print("Creating Phase 3 tables...")
    Base.metadata.create_all(bind=engine)
    print("Done. Tables created (or already existed):")
    for table in [
        "outreach_sequences", "outreach_emails", "conversations",
        "booking_requests", "intent_signals", "ab_test_results", "optimization_runs",
    ]:
        print(f"  ✓ {table}")
