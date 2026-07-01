"""
Lead Processing Queue — Priority Redis Sorted Set

Upgraded from a simple LPUSH/BRPOP list to a Redis sorted set so Hot leads
are processed before Warm and Cold ones, even when they arrive out of order.

Priority scores (higher = dequeued first):
  HOT_PRIORITY     = 80   — verified Hot leads, high-confidence bookings
  WARM_PRIORITY    = 50   — Warm leads, re-engagement triggers
  DEFAULT_PRIORITY = 30   — new inbound leads, unknown verdict
  LOW_PRIORITY     = 10   — IP-visit leads, background re-enrichment

Back-pressure:
  When queue depth exceeds MAX_QUEUE_DEPTH (default 500), push_lead_job raises
  QueueFullError. The ingest endpoints catch this and return HTTP 429, preventing
  unbounded growth during traffic spikes.

Migration note:
  The old list key (QUEUE_KEY = "lead_jobs") is still drained for any items
  that were queued before this upgrade. pop_lead_job checks the sorted set
  first, then falls back to the legacy list.
"""

import json
import redis
from app.config import settings

_client: redis.Redis | None = None

QUEUE_KEY = "lead_jobs"             # legacy list — drained for backward compat
PRIORITY_QUEUE_KEY = "lead_queue:priority"   # new sorted set

WORKER_HEARTBEAT_KEY = "sdr:worker:heartbeat"
WORKER_HEARTBEAT_TTL = 45

MAX_QUEUE_DEPTH = 500

HOT_PRIORITY = 80
WARM_PRIORITY = 50
DEFAULT_PRIORITY = 30
LOW_PRIORITY = 10


class QueueFullError(Exception):
    """Queue is at capacity. Caller should respond with HTTP 429."""


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def push_lead_job(lead_id: str, priority: int = DEFAULT_PRIORITY) -> None:
    """
    Enqueue a lead at the given priority. Higher priority = dequeued sooner.
    NX flag makes this idempotent — a lead already in the queue won't be
    re-added (its existing priority is preserved).
    """
    r = get_redis()
    depth = r.zcard(PRIORITY_QUEUE_KEY) + r.llen(QUEUE_KEY)
    if depth >= MAX_QUEUE_DEPTH:
        raise QueueFullError(
            f"Lead queue at capacity ({depth}/{MAX_QUEUE_DEPTH}). "
            "Retry after the worker drains the backlog."
        )
    r.zadd(PRIORITY_QUEUE_KEY, {lead_id: priority}, nx=True)


def pop_lead_job(timeout: int = 5) -> str | None:
    """
    Pop the highest-priority pending lead. Falls back to the legacy list
    for backward compatibility with items queued before this upgrade.
    Returns the lead_id string, or None on timeout.
    """
    r = get_redis()

    # Sorted set: zpopmax returns [(member, score), ...]
    result = r.zpopmax(PRIORITY_QUEUE_KEY, count=1)
    if result:
        lead_id, _score = result[0]
        return lead_id

    # Legacy BRPOP fallback
    legacy = r.brpop(QUEUE_KEY, timeout=timeout)
    if legacy is None:
        return None
    _, payload = legacy
    try:
        return json.loads(payload)["lead_id"]
    except (json.JSONDecodeError, KeyError):
        return payload


def get_queue_depth() -> int:
    """Total pending jobs across both queue implementations."""
    r = get_redis()
    return r.zcard(PRIORITY_QUEUE_KEY) + r.llen(QUEUE_KEY)


def ping_worker_heartbeat() -> None:
    """Called by the worker every few cycles to signal it is alive."""
    from datetime import datetime, timezone
    get_redis().setex(
        WORKER_HEARTBEAT_KEY,
        WORKER_HEARTBEAT_TTL,
        datetime.now(timezone.utc).isoformat(),
    )


def get_worker_status() -> dict:
    """Returns worker liveness and queue stats for the /health endpoint."""
    try:
        r = get_redis()
        ts = r.get(WORKER_HEARTBEAT_KEY)
        depth = get_queue_depth()
        return {
            "worker_active": ts is not None,
            "worker_last_seen": ts,
            "queue_depth": depth,
            "queue_at_capacity": depth >= MAX_QUEUE_DEPTH,
        }
    except Exception:
        return {
            "worker_active": False,
            "worker_last_seen": None,
            "queue_depth": 0,
            "queue_at_capacity": False,
        }
