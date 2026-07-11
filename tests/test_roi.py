"""
Tests for the ROI analytics endpoint.
"""
from app.database.models import BookingRequest, Lead, LLMCall, Verdict
from app.services.tenancy import get_default_org


def _admin_headers(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed(db):
    org = get_default_org(db)
    for i in range(10):
        lead = Lead(name=f"L{i}", email=f"l{i}@x.com", company="C",
                    status="complete", org_id=org.id,
                    conversion_status="won" if i < 2 else "unqualified")
        db.add(lead)
        db.flush()
        if i < 4:
            db.add(Verdict(lead_id=lead.id, final_verdict="Hot"))
        if i < 3:
            db.add(BookingRequest(lead_id=lead.id))
        db.add(LLMCall(lead_id=lead.id, agent_name="analysis", provider="groq",
                       model="llama-3.1-70b-versatile", prompt_tokens=1000,
                       completion_tokens=500, cost_usd=0.01, latency_ms=500))
    db.commit()


def test_roi_endpoint_math(client, test_session_factory):
    headers = _admin_headers(client)
    db = test_session_factory()
    _seed(db)
    db.close()

    r = client.get("/analytics/roi?days=90&acv=20000&sdr_annual_cost=75000", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["activity"]["leads_processed"] == 10
    assert body["activity"]["hot_leads"] == 4
    assert body["activity"]["meetings_booked"] == 3
    assert body["activity"]["conversions"] == 2
    assert abs(body["activity"]["llm_cost_usd"] - 0.10) < 1e-6

    ue = body["unit_economics"]
    assert abs(ue["ai_cost_per_lead_usd"] - 0.01) < 1e-6
    assert ue["human_cost_per_lead_usd"] == 25.0  # 75000 / 3000
    assert ue["savings_multiple"] == 2500.0
    assert abs(ue["cost_per_meeting_usd"] - (0.10 / 3)) < 1e-4

    assert body["projections"]["pipeline_value_usd"] == 40000.0  # 2 wins x 20k


def test_roi_handles_empty_org(client):
    headers = _admin_headers(client)
    r = client.get("/analytics/roi", headers=headers)
    assert r.status_code == 200
    assert r.json()["activity"]["leads_processed"] == 0
    assert r.json()["unit_economics"]["savings_multiple"] is None


def test_roi_requires_manager(client):
    headers = _admin_headers(client)
    client.post("/auth/register", json={"email": "rep@test.com", "password": "password123", "role": "rep"}, headers=headers)
    r = client.post("/auth/login", json={"email": "rep@test.com", "password": "password123"})
    rep_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/analytics/roi", headers=rep_headers).status_code == 403
