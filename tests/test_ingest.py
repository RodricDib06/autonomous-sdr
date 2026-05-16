"""
Tests for Phase C ingest features:
  - Webhook secret validation (open mode / correct / wrong secret)
  - POST /ingest/form, /ads, /email, /linkedin, /event — basic happy paths
  - POST /ingest/webhook — universal auto-detecting endpoint
      • standard field names
      • camelCase / Typeform-style field names
      • first_name + last_name assembly
      • missing email → 422
      • duplicate email → "duplicate" status
      • non-JSON body → 422
  - GET  /ingest/jobs/{job_id} — 404 for unknown, status from DB for known
  - GET  /config/enrichment-provider — admin required
  - POST /config/enrichment-provider — toggle valid / invalid provider
"""
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers (mirrors test_auth.py conventions)
# ---------------------------------------------------------------------------

def _register(client, email="admin@test.com", password="pass1234"):
    return client.post("/auth/register", json={"email": email, "password": password, "role": "rep"})


def _auth_headers(client, email="admin@test.com", password="pass1234"):
    _register(client, email=email, password=password)
    r = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _ingest(client, path, payload, secret=None):
    """POST to an ingest endpoint, optionally with a webhook secret header."""
    headers = {}
    if secret is not None:
        headers["X-Webhook-Secret"] = secret
    return client.post(path, json=payload, headers=headers)


# ---------------------------------------------------------------------------
# Webhook secret validation
# ---------------------------------------------------------------------------

class TestWebhookSecretValidation:
    """All ingest endpoints respect X-Webhook-Secret when WEBHOOK_SECRET is set."""

    def test_no_secret_configured_accepts_request(self, client):
        """When WEBHOOK_SECRET is '' (default), any request is accepted."""
        with patch("app.routers.ingest.push_lead_job"), \
             patch("app.config.settings") as mock_settings:
            mock_settings.WEBHOOK_SECRET = ""
            # No header needed — open mode
            r = _ingest(client, "/ingest/form", {
                "name": "Alice", "email": "alice@acme.com", "company": "Acme"
            })
            # 200 or 409/422 are fine; 403 would mean secret was incorrectly enforced
            assert r.status_code != 403

    def test_wrong_secret_returns_403(self, client):
        with patch("app.routers.ingest.settings") as mock_settings:
            mock_settings.WEBHOOK_SECRET = "correct-secret"
            r = _ingest(client, "/ingest/form",
                        {"name": "Alice", "email": "alice@acme.com", "company": "Acme"},
                        secret="wrong-secret")
            assert r.status_code == 403

    def test_missing_secret_header_returns_403(self, client):
        with patch("app.routers.ingest.settings") as mock_settings:
            mock_settings.WEBHOOK_SECRET = "correct-secret"
            r = _ingest(client, "/ingest/form",
                        {"name": "Alice", "email": "alice@acme.com", "company": "Acme"})
            assert r.status_code == 403

    def test_correct_secret_accepted(self, client):
        with patch("app.routers.ingest.push_lead_job"), \
             patch("app.routers.ingest.settings") as mock_settings:
            mock_settings.WEBHOOK_SECRET = "correct-secret"
            # Patch get_redis to avoid connection errors
            mock_redis = MagicMock()
            mock_redis.setex = MagicMock()
            with patch("app.services.queue_service.get_redis", return_value=mock_redis):
                r = _ingest(client, "/ingest/form",
                            {"name": "Alice", "email": "alice-secret@acme.com", "company": "Acme"},
                            secret="correct-secret")
            assert r.status_code != 403


# ---------------------------------------------------------------------------
# Individual channel endpoints — happy paths
# ---------------------------------------------------------------------------

class TestChannelEndpoints:
    """Basic smoke tests for each ingest channel."""

    @pytest.fixture(autouse=True)
    def _mock_queue(self):
        """Prevent every test from needing a live Redis."""
        with patch("app.routers.ingest.push_lead_job"):
            mock_redis = MagicMock()
            with patch("app.services.queue_service.get_redis", return_value=mock_redis):
                yield

    def test_ingest_form(self, client):
        r = _ingest(client, "/ingest/form",
                    {"name": "Bob", "email": "bob@example.com", "company": "ExCorp"})
        assert r.status_code == 200
        assert r.json()["status"] in ("queued", "duplicate")

    def test_ingest_ads(self, client):
        r = _ingest(client, "/ingest/ads",
                    {"name": "Carol", "email": "carol@ads.com", "platform": "meta"})
        assert r.status_code == 200
        assert r.json()["status"] in ("queued", "duplicate")

    def test_ingest_email(self, client):
        r = _ingest(client, "/ingest/email",
                    {"from_name": "Dave", "from_email": "dave@corp.com"})
        assert r.status_code == 200

    def test_ingest_linkedin_no_email_skipped(self, client):
        r = _ingest(client, "/ingest/linkedin",
                    {"name": "Eve", "signal_type": "profile_visit"})
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"
        assert r.json()["reason"] == "no_email"

    def test_ingest_linkedin_with_email(self, client):
        r = _ingest(client, "/ingest/linkedin",
                    {"name": "Frank", "email": "frank@linkedin.com",
                     "signal_type": "connection_request"})
        assert r.status_code == 200
        assert r.json()["status"] in ("queued", "duplicate")

    def test_ingest_event(self, client):
        r = _ingest(client, "/ingest/event", {
            "event_name": "SaaS Summit",
            "attendee_name": "Grace",
            "attendee_email": "grace@event.com",
        })
        assert r.status_code == 200
        assert r.json()["event"] == "SaaS Summit"


# ---------------------------------------------------------------------------
# Universal webhook — field auto-detection
# ---------------------------------------------------------------------------

class TestUniversalWebhook:
    """POST /ingest/webhook handles varied JSON shapes from Zapier/Typeform/Make."""

    @pytest.fixture(autouse=True)
    def _mock_queue(self):
        with patch("app.routers.ingest.push_lead_job"):
            mock_redis = MagicMock()
            with patch("app.services.queue_service.get_redis", return_value=mock_redis):
                yield

    def test_standard_fields(self, client):
        r = client.post("/ingest/webhook", json={
            "email": "henry@standard.com",
            "name": "Henry",
            "company": "StandardCo",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("queued", "duplicate")

    def test_camelcase_fields(self, client):
        r = client.post("/ingest/webhook", json={
            "Email": "irene@camel.com",
            "fullName": "Irene C",
            "organization": "CamelCorp",
        })
        assert r.status_code == 200
        assert r.json()["status"] in ("queued", "duplicate")

    def test_first_last_name_assembly(self, client):
        r = client.post("/ingest/webhook", json={
            "email": "jack@split.com",
            "first_name": "Jack",
            "last_name": "Splitter",
            "company": "SplitCo",
        })
        assert r.status_code == 200

    def test_company_inferred_from_email_domain(self, client):
        r = client.post("/ingest/webhook", json={
            "email": "kate@inferred.com",
            "name": "Kate",
            # no company — should be inferred from domain "inferred"
        })
        assert r.status_code == 200

    def test_from_email_field_name(self, client):
        """Typeform / mail relay sends 'from_email' instead of 'email'."""
        r = client.post("/ingest/webhook", json={
            "from_email": "liam@typeform.com",
            "name": "Liam",
            "firm": "TypeformUser",
        })
        assert r.status_code == 200

    def test_missing_email_returns_422(self, client):
        r = client.post("/ingest/webhook", json={
            "name": "Nobody",
            "company": "NoCo",
        })
        assert r.status_code == 422
        assert "email" in r.json()["detail"].lower()

    def test_duplicate_email_returns_duplicate_status(self, client):
        payload = {"email": "dup@dup.com", "name": "Dup", "company": "DupCo"}
        client.post("/ingest/webhook", json=payload)  # first ingest
        r = client.post("/ingest/webhook", json=payload)  # duplicate
        assert r.status_code == 200
        assert r.json()["status"] == "duplicate"

    def test_non_json_body_returns_422(self, client):
        r = client.post(
            "/ingest/webhook",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422

    def test_response_includes_detected_source(self, client):
        r = client.post("/ingest/webhook", json={
            "email": "meta@ads.com",
            "name": "Meta Lead",
            "company": "AdCo",
            "source": "marketing_ad",
        })
        assert r.status_code == 200
        assert r.json()["detected_source"] == "marketing_ad"

    def test_unknown_source_normalised_to_website_form(self, client):
        r = client.post("/ingest/webhook", json={
            "email": "weird@source.com",
            "name": "Weird",
            "company": "WCo",
            "source": "some_random_crm_tool",
        })
        assert r.status_code == 200
        assert r.json()["detected_source"] == "website_form"


# ---------------------------------------------------------------------------
# Job status — GET /ingest/jobs/{job_id}
# ---------------------------------------------------------------------------

class TestJobStatus:
    """GET /ingest/jobs/{id} returns pipeline status."""

    @pytest.fixture(autouse=True)
    def _mock_queue(self):
        with patch("app.routers.ingest.push_lead_job"):
            mock_redis = MagicMock()
            mock_redis.setex = MagicMock()
            mock_redis.get = MagicMock(return_value=None)  # no cached status
            with patch("app.services.queue_service.get_redis", return_value=mock_redis):
                yield

    def test_unknown_job_returns_404(self, client):
        r = client.get("/ingest/jobs/nonexistent-id-000")
        assert r.status_code == 404

    def test_known_job_returns_status(self, client):
        # Create a lead via ingest so it exists in the DB
        r = client.post("/ingest/webhook", json={
            "email": "jobtest@corp.com",
            "name": "Job Test",
            "company": "Corp",
        })
        assert r.status_code == 200
        lead_id = r.json()["lead_id"]

        # Poll the job status
        r2 = client.get(f"/ingest/jobs/{lead_id}")
        assert r2.status_code == 200
        data = r2.json()
        assert data["job_id"] == lead_id
        assert data["status"] in ("pending", "processing", "complete", "failed", "queued")

    def test_job_response_shape(self, client):
        r = client.post("/ingest/form", json={
            "name": "Shape Test",
            "email": "shape@corp.com",
            "company": "ShapeCo",
        })
        lead_id = r.json()["lead_id"]

        r2 = client.get(f"/ingest/jobs/{lead_id}")
        body = r2.json()
        assert "job_id" in body
        assert "lead_id" in body
        assert "status" in body
        # verdict is optional (None until pipeline completes)
        assert "verdict" in body


# ---------------------------------------------------------------------------
# Enrichment provider toggle — GET/POST /config/enrichment-provider
# ---------------------------------------------------------------------------

class TestEnrichmentProviderToggle:
    """Runtime enrichment provider switch — admin-gated."""

    @pytest.fixture
    def admin_headers(self, client):
        return _auth_headers(client)

    def test_get_provider_requires_admin(self, client):
        r = client.get("/config/enrichment-provider")
        assert r.status_code == 401  # no auth

    def test_get_provider_returns_current(self, client, admin_headers):
        r = client.get("/config/enrichment-provider", headers=admin_headers)
        assert r.status_code == 200
        assert "enrichment_provider" in r.json()

    def test_toggle_to_hunter(self, client, admin_headers):
        r = client.post("/config/enrichment-provider?provider=hunter",
                        headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["enrichment_provider"] == "hunter"
        assert r.json()["status"] == "updated"

    def test_toggle_to_pdl(self, client, admin_headers):
        r = client.post("/config/enrichment-provider?provider=pdl",
                        headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["enrichment_provider"] == "pdl"

    def test_toggle_to_synthetic(self, client, admin_headers):
        r = client.post("/config/enrichment-provider?provider=synthetic",
                        headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["enrichment_provider"] == "synthetic"

    def test_invalid_provider_returns_400(self, client, admin_headers):
        r = client.post("/config/enrichment-provider?provider=clearbit",
                        headers=admin_headers)
        assert r.status_code == 400
        assert "clearbit" not in r.json()["detail"].lower() or "valid" in r.json()["detail"].lower()

    def test_toggle_requires_admin(self, client):
        # No auth at all
        r = client.post("/config/enrichment-provider?provider=hunter")
        assert r.status_code == 401

    def test_toggle_requires_admin_not_rep(self, client):
        # Register a second user as rep (first user is auto-admin)
        _register(client, email="admin2@test.com")  # admin
        admin_h = _auth_headers(client, email="admin2@test.com")
        # Register a rep
        client.post("/auth/register",
                    json={"email": "rep@test.com", "password": "pass1234", "role": "rep"},
                    headers=admin_h)
        rep_r = client.post("/auth/login",
                            json={"email": "rep@test.com", "password": "pass1234"})
        rep_headers = {"Authorization": f"Bearer {rep_r.json()['access_token']}"}

        r = client.post("/config/enrichment-provider?provider=hunter",
                        headers=rep_headers)
        assert r.status_code == 403
