"""
Single choke point for "now" in application code.

DB columns are naive-UTC DateTime, so this returns a naive UTC datetime —
but via the non-deprecated timezone-aware API. When the schema migrates to
timestamptz, only this function changes.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
