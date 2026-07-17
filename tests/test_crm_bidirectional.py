"""
Tests for bidirectional HubSpot sync (ROADMAP 9.1) + read-only demo guard.

Coverage:
  - webhook signature v3: valid, wrong secret, stale timestamp, missing
  - inbound events: lifecyclestage → conversion_status with LeadHistory +
    sync log; unmapped stages ignored; unknown portal ignored; contact
    resolved by email once then remembered; deal closedwon via associations
  - conflict policy: CRM overwrites conversion_status, never verdict/scores
  - outbound push: create captures contact id, 409 recovers existing id,
    failure is logged not raised
  - OAuth: start requires config, callback stores encrypted connection
  - status/log endpoints, RBAC + org scoping
  - DEMO_READONLY_EMAILS: GET allowed, mutation 403
"""

import base64
import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

from app.database.models import CrmConnection, CrmSyncLog, Lead, LeadHistory, Verdict
from app.services import hubspot_sync as hs
from app.services.mailbox_service import encrypt_secret
from app.services.tenancy import get_default_org
from app.utils.time import utcnow


def _connection(db, org_id, portal="12345"):
    blob = {"access_token": "at-1", "refresh_token": "rt-1",
            "expires_at": (utcnow() + timedelta(hours=1)).isoformat()}
    connection = CrmConnection(
        org_id=org_id, provider="hubspot", portal_id=portal,
        token_encrypted=encrypt_secret(json.dumps(blob)),
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


def _lead(db, org_id=None, email="jane@acme.io", **kwargs):
    lead = Lead(name="Jane Doe", email=email, company="Acme", org_id=org_id, **kwargs)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _sign(body: bytes, uri: str, secret: str, ts_ms: int | None = None) -> tuple[str, str]:
    ts = str(ts_ms if ts_ms is not None else int(utcnow().timestamp() * 1000))
    message = "POST" + uri + body.decode() + ts
    sig = base64.b64encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()).decode()
    return sig, ts


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------

def test_signature_v3_roundtrip(monkeypatch):
    monkeypatch.setattr(hs.settings, "HUBSPOT_CLIENT_SECRET", "s3cret")
    body, uri = b'[{"objectId": 1}]', "https://x.example/ingest/hubspot-webhook"
    sig, ts = _sign(body, uri, "s3cret")
    assert hs.validate_signature_v3("POST", uri, body, ts, sig) is True
    assert hs.validate_signature_v3("POST", uri, body, ts, "bogus") is False
    wrong, _ = _sign(body, uri, "other-secret")
    assert hs.validate_signature_v3("POST", uri, body, ts, wrong) is False


def test_signature_rejects_stale_and_missing(monkeypatch):
    monkeypatch.setattr(hs.settings, "HUBSPOT_CLIENT_SECRET", "s3cret")
    body, uri = b"[]", "https://x.example/hook"
    stale_ms = int((utcnow() - timedelta(minutes=10)).timestamp() * 1000)
    sig, ts = _sign(body, uri, "s3cret", ts_ms=stale_ms)
    assert hs.validate_signature_v3("POST", uri, body, ts, sig) is False
    assert hs.validate_signature_v3("POST", uri, body, "", sig) is False
    monkeypatch.setattr(hs.settings, "HUBSPOT_CLIENT_SECRET", "")
    sig, ts = _sign(body, uri, "s3cret")
    assert hs.validate_signature_v3("POST", uri, body, ts, sig) is False


# ---------------------------------------------------------------------------
# Inbound events
# ---------------------------------------------------------------------------

def _lifecycle_event(portal="12345", object_id="901", value="customer"):
    return {"portalId": portal, "subscriptionType": "contact.propertyChange",
            "propertyName": "lifecyclestage", "objectId": object_id,
            "propertyValue": value}


def test_lifecycle_event_updates_conversion(test_db):
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    lead = _lead(test_db, org_id=org.id, hubspot_contact_id="901")

    summary = hs.process_webhook_events(test_db, [_lifecycle_event(value="customer")])

    assert summary["updated"] == 1
    test_db.refresh(lead)
    assert lead.conversion_status == "won"
    history = test_db.query(LeadHistory).filter_by(lead_id=lead.id).first()
    assert history.old_value == "unqualified" and history.new_value == "won"
    entry = test_db.query(CrmSyncLog).filter_by(direction="inbound").first()
    assert entry.event_type == "contact.lifecyclestage"
    assert entry.payload["applied"] is True


def test_unmapped_stage_and_unknown_portal_ignored(test_db):
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    lead = _lead(test_db, org_id=org.id, hubspot_contact_id="901")

    summary = hs.process_webhook_events(test_db, [
        _lifecycle_event(value="subscriber"),          # unmapped stage
        _lifecycle_event(portal="99999"),              # unknown portal
    ])
    assert summary["updated"] == 0 and summary["skipped"] == 2
    test_db.refresh(lead)
    assert lead.conversion_status == "unqualified"


def test_unknown_contact_resolved_by_email_then_remembered(test_db):
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    lead = _lead(test_db, org_id=org.id)  # no hubspot_contact_id yet

    with patch.object(hs, "_fetch_contact_email", return_value="jane@acme.io"):
        summary = hs.process_webhook_events(test_db, [_lifecycle_event(object_id="777")])

    assert summary["updated"] == 1
    test_db.refresh(lead)
    assert lead.hubspot_contact_id == "777"
    assert lead.conversion_status == "won"

    # Second event: no email lookup needed any more
    with patch.object(hs, "_fetch_contact_email", side_effect=AssertionError("should not fetch")):
        hs.process_webhook_events(test_db, [_lifecycle_event(object_id="777", value="opportunity")])
    test_db.refresh(lead)
    assert lead.conversion_status == "qualified"


def test_deal_closedwon_via_associations(test_db):
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    lead = _lead(test_db, org_id=org.id, hubspot_contact_id="901")

    event = {"portalId": "12345", "subscriptionType": "deal.propertyChange",
             "propertyName": "dealstage", "objectId": "555",
             "propertyValue": "closedwon"}
    with patch.object(hs, "_deal_contact_ids", return_value=["901"]):
        summary = hs.process_webhook_events(test_db, [event])

    assert summary["updated"] == 1
    test_db.refresh(lead)
    assert lead.conversion_status == "won"


def test_conflict_policy_never_touches_scores(test_db):
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    lead = _lead(test_db, org_id=org.id, hubspot_contact_id="901")
    lead.data_quality_score = 0.9
    test_db.add(Verdict(lead_id=lead.id, final_verdict="Hot", confidence_score=0.88))
    test_db.commit()

    hs.process_webhook_events(test_db, [_lifecycle_event(value="customer")])

    test_db.refresh(lead)
    assert lead.conversion_status == "won"           # CRM won on stage
    assert lead.data_quality_score == 0.9            # platform kept its scores
    verdict = test_db.query(Verdict).filter_by(lead_id=lead.id).first()
    assert verdict.final_verdict == "Hot" and verdict.confidence_score == 0.88


def test_idempotent_reapply_logs_but_does_not_duplicate_history(test_db):
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    lead = _lead(test_db, org_id=org.id, hubspot_contact_id="901")

    hs.process_webhook_events(test_db, [_lifecycle_event(value="customer")])
    hs.process_webhook_events(test_db, [_lifecycle_event(value="customer")])

    assert test_db.query(LeadHistory).filter_by(lead_id=lead.id).count() == 1


# ---------------------------------------------------------------------------
# Outbound push
# ---------------------------------------------------------------------------

def _payload(lead):
    return {"email": lead.email, "first_name": "Jane", "last_name": "Doe",
            "company": lead.company, "job_title": "VP", "verdict": "Hot"}


def test_push_creates_contact_and_captures_id(test_db):
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    lead = _lead(test_db, org_id=org.id)

    created = MagicMock(status_code=201, ok=True)
    created.json.return_value = {"id": "424242"}
    with patch.object(hs.requests, "post", return_value=created):
        result = hs.push_contact(test_db, lead, _payload(lead))

    assert result == {"crm": "hubspot", "status": "created", "external_id": "424242"}
    test_db.refresh(lead)
    assert lead.hubspot_contact_id == "424242"
    entry = test_db.query(CrmSyncLog).filter_by(direction="outbound").first()
    assert entry.event_type == "contact.created"


def test_push_409_recovers_existing_contact(test_db):
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    lead = _lead(test_db, org_id=org.id)

    conflict = MagicMock(status_code=409, ok=False)
    conflict.json.return_value = {"message": "Contact already exists. Existing ID: 777888"}
    patched = MagicMock(status_code=200, ok=True)
    with patch.object(hs.requests, "post", return_value=conflict), \
         patch.object(hs.requests, "patch", return_value=patched):
        result = hs.push_contact(test_db, lead, _payload(lead))

    assert result["status"] == "updated"
    assert result["external_id"] == "777888"
    test_db.refresh(lead)
    assert lead.hubspot_contact_id == "777888"


def test_push_failure_logged_not_raised(test_db):
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    lead = _lead(test_db, org_id=org.id)

    with patch.object(hs.requests, "post", side_effect=RuntimeError("network down")):
        result = hs.push_contact(test_db, lead, _payload(lead))

    assert result["status"] == "failed"
    entry = test_db.query(CrmSyncLog).filter_by(success=False).first()
    assert "network down" in entry.error_message


def test_push_without_any_auth_is_noop(test_db, monkeypatch):
    monkeypatch.setattr(hs.settings, "HUBSPOT_API_KEY", "")
    lead = _lead(test_db)
    assert hs.push_contact(test_db, lead, _payload(lead))["status"] == "not_configured"


# ---------------------------------------------------------------------------
# API: OAuth, status, log, webhook, RBAC
# ---------------------------------------------------------------------------

def _login(client, email="admin@test.com"):
    client.post("/auth/register", json={"email": email, "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_oauth_start_requires_config(client, monkeypatch):
    headers = _login(client)
    monkeypatch.setattr(hs.settings, "HUBSPOT_CLIENT_ID", "")
    r = client.get("/crm/hubspot/start", headers=headers)
    assert r.status_code == 400
    assert "HUBSPOT_CLIENT_ID" in r.json()["detail"]


def test_oauth_start_and_callback_create_connection(client, test_db, monkeypatch):
    monkeypatch.setattr(hs.settings, "HUBSPOT_CLIENT_ID", "cid")
    monkeypatch.setattr(hs.settings, "HUBSPOT_CLIENT_SECRET", "csecret")
    headers = _login(client)

    r = client.get("/crm/hubspot/start", headers=headers,
                   params={"redirect_uri": "https://app/crm/hubspot/callback"})
    assert r.status_code == 200, r.text
    assert r.json()["authorize_url"].startswith("https://app.hubspot.com/oauth/authorize?")
    state = r.json()["state"]

    blob = {"access_token": "at-1", "refresh_token": "rt-1",
            "expires_at": (utcnow() + timedelta(minutes=30)).isoformat()}
    with patch.object(hs, "exchange_code", return_value=blob), \
         patch.object(hs, "fetch_portal_id", return_value="12345"):
        # router imports these at module level — patch through the router too
        with patch("app.routers.crm.exchange_code", return_value=blob), \
             patch("app.routers.crm.fetch_portal_id", return_value="12345"):
            r = client.get("/crm/hubspot/callback", params={"code": "c", "state": state})

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "connected", "portal_id": "12345"}
    connection = test_db.query(CrmConnection).first()
    assert connection.portal_id == "12345"
    assert "at-1" not in connection.token_encrypted  # encrypted at rest

    r = client.get("/crm/status", headers=headers)
    assert r.json()["hubspot"]["connected"] is True
    assert r.json()["hubspot"]["portal_id"] == "12345"


def test_webhook_endpoint_validates_signature(client, test_db, monkeypatch):
    monkeypatch.setattr(hs.settings, "HUBSPOT_CLIENT_SECRET", "s3cret")
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    _lead(test_db, org_id=org.id, hubspot_contact_id="901")

    body = json.dumps([_lifecycle_event(value="customer")]).encode()
    # TestClient URL for signature purposes
    uri = "http://testserver/ingest/hubspot-webhook"
    sig, ts = _sign(body, uri, "s3cret")

    r = client.post("/ingest/hubspot-webhook", content=body,
                    headers={"X-HubSpot-Signature-v3": sig,
                             "X-HubSpot-Request-Timestamp": ts,
                             "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1

    r = client.post("/ingest/hubspot-webhook", content=body,
                    headers={"X-HubSpot-Signature-v3": "forged",
                             "X-HubSpot-Request-Timestamp": ts})
    assert r.status_code == 401


def test_crm_log_and_disconnect(client, test_db):
    headers = _login(client)
    org = get_default_org(test_db)
    _connection(test_db, org.id)
    hs.log_sync(test_db, org_id=org.id, direction="outbound",
                event_type="contact.created", external_id="1")

    r = client.get("/crm/log", headers=headers)
    assert len(r.json()["entries"]) == 1

    r = client.delete("/crm/hubspot", headers=headers)
    assert r.json()["status"] == "disconnected"
    assert client.get("/crm/status", headers=headers).json()["hubspot"]["connected"] is False


def test_crm_requires_auth(client):
    assert client.get("/crm/status").status_code in (401, 403)
    assert client.get("/crm/hubspot/start").status_code in (401, 403)


# ---------------------------------------------------------------------------
# Read-only demo accounts
# ---------------------------------------------------------------------------

def test_demo_readonly_account_can_read_but_not_mutate(client, monkeypatch):
    headers = _login(client, email="demo@test.com")
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "DEMO_READONLY_EMAILS", "demo@test.com")

    assert client.get("/crm/status", headers=headers).status_code == 200
    r = client.put("/outreach/autonomy", json={"mode": "auto"}, headers=headers)
    assert r.status_code == 403
    assert "read-only demo" in r.json()["detail"]
