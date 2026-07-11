"""
Tests for GDPR erasure, retention purge, and audit endpoints.
"""
import hashlib
from datetime import timedelta
from unittest.mock import patch

from app.database.models import (
    Enrichment,
    GdprErasureLog,
    Lead,
    LeadEvent,
    LLMCall,
    OutreachEmail,
    SuppressionEntry,
)
from app.services.gdpr_service import erase_lead, purge_expired_leads
from app.services.tenancy import get_default_org
from app.utils.time import utcnow


def _make_full_lead(db, org_id, email="jane@acme.com"):
    lead = Lead(name="Jane", email=email, company="Acme", org_id=org_id)
    db.add(lead)
    db.flush()
    db.add(Enrichment(lead_id=lead.id, job_title="VP"))
    db.add(OutreachEmail(lead_id=lead.id, step_number=1, subject="s", body="b", status="sent"))
    db.add(LeadEvent(lead_id=lead.id, event_type="pipeline.complete", payload={"x": 1}))
    db.add(LLMCall(lead_id=lead.id, provider="groq", model="llama-3.1-70b",
                   prompt_tokens=10, completion_tokens=5, cost_usd=0.001, latency_ms=100))
    db.add(SuppressionEntry(value=email, kind="email", lead_id=lead.id, org_id=org_id))
    db.commit()
    db.refresh(lead)
    return lead


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def test_erase_lead_removes_pii_keeps_telemetry(test_db):
    org = get_default_org(test_db)
    lead = _make_full_lead(test_db, org.id)
    lead_id = lead.id

    result = erase_lead(test_db, lead, requested_by_id=None)

    assert test_db.query(Lead).filter_by(id=lead_id).first() is None
    assert test_db.query(Enrichment).count() == 0
    assert test_db.query(OutreachEmail).count() == 0
    assert test_db.query(LeadEvent).count() == 0

    # Telemetry kept but anonymised
    call = test_db.query(LLMCall).one()
    assert call.lead_id is None

    # Do-not-contact survives erasure, unlinked
    entry = test_db.query(SuppressionEntry).one()
    assert entry.lead_id is None
    assert entry.value == "jane@acme.com"

    # Audit row with hashed email only
    audit = test_db.query(GdprErasureLog).one()
    assert audit.email_hash == hashlib.sha256(b"jane@acme.com").hexdigest()
    assert audit.purged_counts["enrichments"] == 1
    assert result["purged"]["outreach_emails"] == 1


def test_retention_purge_respects_exemptions(test_db):
    org = get_default_org(test_db)

    old_lost = Lead(name="Old", email="old@x.com", company="C", org_id=org.id,
                    created_at=utcnow() - timedelta(days=400))
    old_won = Lead(name="Won", email="won@x.com", company="C", org_id=org.id,
                   conversion_status="won", created_at=utcnow() - timedelta(days=400))
    fresh = Lead(name="New", email="new@x.com", company="C", org_id=org.id)
    test_db.add_all([old_lost, old_won, fresh])
    test_db.commit()

    with patch("app.config.settings.DATA_RETENTION_DAYS", 365):
        summary = purge_expired_leads(test_db)

    assert summary["purged"] == 1
    remaining = {ld.email for ld in test_db.query(Lead).all()}
    assert remaining == {"won@x.com", "new@x.com"}


def test_retention_purge_disabled_by_default(test_db):
    summary = purge_expired_leads(test_db)
    assert summary == {"purged": 0, "enabled": False}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _admin_headers(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_erase_endpoint(client, test_session_factory):
    headers = _admin_headers(client)
    db = test_session_factory()
    lead = _make_full_lead(db, get_default_org(db).id)
    lead_id = lead.id
    db.close()

    r = client.delete(f"/gdpr/leads/{lead_id}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "erased"

    assert client.delete(f"/gdpr/leads/{lead_id}", headers=headers).status_code == 404

    r = client.get("/gdpr/erasures", headers=headers)
    assert r.json()["total"] == 1
    assert "@" not in r.json()["erasures"][0]["email_hash"]


def test_erase_requires_admin(client):
    headers = _admin_headers(client)
    client.post("/auth/register", json={"email": "mgr@test.com", "password": "password123", "role": "manager"}, headers=headers)
    r = client.post("/auth/login", json={"email": "mgr@test.com", "password": "password123"})
    mgr_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.delete("/gdpr/leads/whatever", headers=mgr_headers).status_code == 403


def test_audit_log_export(client, test_session_factory):
    headers = _admin_headers(client)
    db = test_session_factory()
    _make_full_lead(db, get_default_org(db).id)
    db.close()

    r = client.get("/gdpr/audit-log", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["events"][0]["event_type"] == "pipeline.complete"

    r = client.get("/gdpr/audit-log?format=csv", headers=headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "pipeline.complete" in r.text
