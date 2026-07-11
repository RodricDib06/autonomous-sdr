"""
Tests for LLM cost tracking: token estimation, pricing, tracked client
recording (incl. attribution via agent context), and analytics endpoints.
"""
from unittest.mock import patch

from app.database.models import Lead, LLMCall
from app.services.llm_tracker import (
    TrackedAIClient,
    cost_usd,
    estimate_tokens,
    reset_llm_context,
    set_llm_context,
)


class FakeClient:
    model = "llama-3.1-70b-versatile"

    def generate(self, prompt: str, *a, **k) -> str:
        return "a completion " * 10


class ExplodingClient:
    model = "llama-3.1-70b-versatile"

    def generate(self, prompt: str, *a, **k) -> str:
        raise RuntimeError("rate limited")


def test_estimate_tokens():
    assert estimate_tokens("x" * 400) == 100
    assert estimate_tokens("") == 1


def test_cost_usd_prefix_matching():
    # 1M prompt + 1M completion tokens of llama-3.1-70b = $0.59 + $0.79
    assert abs(cost_usd("llama-3.1-70b-versatile", 1_000_000, 1_000_000) - 1.38) < 1e-9
    assert cost_usd("claude-sonnet-5", 1_000_000, 0) == 3.0
    assert cost_usd("unknown-model", 1_000_000, 1_000_000) == 0.0
    assert cost_usd("mistral:7b", 1_000_000, 1_000_000) == 0.0  # local


def _patch_session(test_session_factory):
    return patch("app.database.connection.SessionLocal", test_session_factory)


def test_tracked_client_records_call(test_db, test_session_factory):
    client = TrackedAIClient(FakeClient(), "groq")
    with _patch_session(test_session_factory):
        out = client.generate("hello world " * 50)

    assert "completion" in out
    row = test_db.query(LLMCall).one()
    assert row.provider == "groq"
    assert row.model.startswith("llama")
    assert row.prompt_tokens > 0 and row.completion_tokens > 0
    assert row.cost_usd > 0
    assert row.success is True


def test_tracked_client_records_failures(test_db, test_session_factory):
    client = TrackedAIClient(ExplodingClient(), "groq")
    with _patch_session(test_session_factory):
        try:
            client.generate("boom")
        except RuntimeError:
            pass

    row = test_db.query(LLMCall).one()
    assert row.success is False
    assert "rate limited" in row.error_message


def test_context_attributes_lead_and_agent(test_db, test_session_factory):
    lead = Lead(name="J", email="j@x.com", company="C")
    test_db.add(lead)
    test_db.commit()

    client = TrackedAIClient(FakeClient(), "groq")
    ctx = set_llm_context(lead.id, "analysis")
    try:
        with _patch_session(test_session_factory):
            client.generate("prompt")
    finally:
        reset_llm_context(ctx)

    row = test_db.query(LLMCall).one()
    assert row.lead_id == lead.id
    assert row.agent_name == "analysis"


def test_recording_failure_never_raises():
    client = TrackedAIClient(FakeClient(), "groq")
    with patch("app.services.llm_tracker.record_llm_call", side_effect=None):
        assert client.generate("hi")  # no exception even if DB unavailable


def test_passthrough_attributes():
    client = TrackedAIClient(FakeClient(), "groq")
    assert client.model == "llama-3.1-70b-versatile"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _admin_headers(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_calls(db, lead_id=None):
    for agent, cost in (("analysis", 0.002), ("outreach", 0.001), ("analysis", 0.003)):
        db.add(LLMCall(
            lead_id=lead_id, agent_name=agent, provider="groq",
            model="llama-3.1-70b-versatile", prompt_tokens=1000,
            completion_tokens=500, cost_usd=cost, latency_ms=800,
        ))
    db.commit()


def test_llm_costs_endpoint(client, test_session_factory):
    headers = _admin_headers(client)
    db = test_session_factory()
    _seed_calls(db)
    db.close()

    r = client.get("/analytics/llm-costs", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_calls"] == 3
    assert abs(body["total_cost_usd"] - 0.006) < 1e-6
    agents = {a["agent"]: a for a in body["by_agent"]}
    assert agents["analysis"]["calls"] == 2
    assert body["by_model"][0]["provider"] == "groq"


def test_lead_llm_cost_endpoint(client, test_session_factory):
    headers = _admin_headers(client)
    db = test_session_factory()
    lead = Lead(name="J", email="j@x.com", company="C")
    db.add(lead)
    db.commit()
    _seed_calls(db, lead_id=lead.id)
    lead_id = lead.id
    db.close()

    r = client.get(f"/leads/{lead_id}/llm-cost", headers=headers)
    assert r.status_code == 200
    assert r.json()["calls"] == 3
    assert abs(r.json()["cost_usd"] - 0.006) < 1e-6
