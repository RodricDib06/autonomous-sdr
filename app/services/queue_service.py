import json
import redis
from app.config import settings

_client: redis.Redis | None = None

QUEUE_KEY = "lead_jobs"
WORKER_HEARTBEAT_KEY = "sdr:worker:heartbeat"
WORKER_HEARTBEAT_TTL = 45  # seconds — worker pings every ~15s, declare dead after 45s


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def push_lead_job(lead_id: str) -> None:
    payload = json.dumps({"lead_id": lead_id})
    get_redis().lpush(QUEUE_KEY, payload)


def pop_lead_job(timeout: int = 5) -> str | None:
    result = get_redis().brpop(QUEUE_KEY, timeout=timeout)
    if result is None:
        return None
    _, payload = result
    data = json.loads(payload)
    return data["lead_id"]


def ping_worker_heartbeat() -> None:
    """Called by the worker every few cycles to signal it is alive."""
    from datetime import datetime, timezone
    get_redis().setex(
        WORKER_HEARTBEAT_KEY,
        WORKER_HEARTBEAT_TTL,
        datetime.now(timezone.utc).isoformat(),
    )


def get_worker_status() -> dict:
    """Returns worker liveness for the /health endpoint."""
    try:
        ts = get_redis().get(WORKER_HEARTBEAT_KEY)
        return {"worker_active": ts is not None, "worker_last_seen": ts}
    except Exception:
        return {"worker_active": False, "worker_last_seen": None}
