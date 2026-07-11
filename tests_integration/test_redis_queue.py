"""
Real-Redis integration tests for the priority lead queue and job locks.
"""

import uuid

import pytest

pytestmark = pytest.mark.integration


def test_queue_push_pop_roundtrip(redis_client):
    from app.services.queue_service import pop_lead_job, push_lead_job

    lead_id = f"it-{uuid.uuid4().hex}"
    push_lead_job(lead_id)

    seen = []
    for _ in range(50):  # drain up to 50 items looking for ours
        item = pop_lead_job(timeout=1)
        if item is None:
            break
        seen.append(item)
        if item == lead_id:
            break

    assert lead_id in seen
    # put back anything else we drained
    for other in seen:
        if other != lead_id:
            push_lead_job(other)


def test_scheduler_lock_single_winner(redis_client):
    key = f"asdr:job_lock:it-{uuid.uuid4().hex[:8]}"
    first = redis_client.set(key, "a", nx=True, ex=5)
    second = redis_client.set(key, "b", nx=True, ex=5)
    assert first is True
    assert second is None
    redis_client.delete(key)
