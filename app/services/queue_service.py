import json
import redis
from app.config import settings

_client: redis.Redis | None = None

QUEUE_KEY = "lead_jobs"


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
