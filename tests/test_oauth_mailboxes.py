"""
Tests for OAuth mailboxes (Gmail API / Microsoft Graph).

Coverage:
  - signed state: round-trip, provider mismatch, tampering
  - authorize URL construction (offline access for Google)
  - code exchange → encrypted-ready token blob; refresh-token requirement
  - access-token refresh: fresh reuse, expiry → refresh + re-persist,
    Microsoft refresh-token rotation
  - send_mime dispatch to the right API per provider
  - send_via_mailbox routes OAuth mailboxes away from SMTP
  - reply poller consumes OAuth mailboxes: replies matched, bounces handled,
    messages acknowledged
  - router: start (config + RBAC guards), callback (create + reconnect)

All HTTP is mocked — no test talks to Google or Microsoft.
"""

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.database.models import Lead, OutreachEmail, SendingMailbox
from app.services import oauth_mailbox as om
from app.services.mailbox_service import decrypt_secret, encrypt_secret
from app.utils.time import utcnow


@pytest.fixture(autouse=True)
def _oauth_settings(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_ID", "ms-client-id")
    monkeypatch.setattr(settings, "MICROSOFT_CLIENT_SECRET", "ms-secret")


def _token_blob(provider="gmail", expires_in_seconds=3600):
    return {
        "provider": provider,
        "access_token": "at-1",
        "refresh_token": "rt-1",
        "expires_at": (utcnow() + timedelta(seconds=expires_in_seconds)).isoformat(),
    }


def _oauth_mailbox(db, provider="gmail_oauth", email="rep@company.com", org_id=None, **blob_kwargs):
    mailbox = SendingMailbox(
        email=email, provider=provider, org_id=org_id,
        smtp_host="", smtp_username=email,
        smtp_password_encrypted=encrypt_secret(json.dumps(
            _token_blob("gmail" if provider == "gmail_oauth" else "microsoft", **blob_kwargs)
        )),
    )
    db.add(mailbox)
    db.commit()
    db.refresh(mailbox)
    return mailbox


# ---------------------------------------------------------------------------
# State + authorize URL
# ---------------------------------------------------------------------------

def test_state_round_trip():
    state = om.create_state("user-1", "org-1", "gmail", "https://app/cb")
    payload = om.decode_state(state, "gmail")
    assert payload["sub"] == "user-1"
    assert payload["org"] == "org-1"
    assert payload["redirect_uri"] == "https://app/cb"


def test_state_provider_mismatch_rejected():
    state = om.create_state("user-1", None, "gmail", "https://app/cb")
    with pytest.raises(ValueError):
        om.decode_state(state, "microsoft")


def test_tampered_state_rejected():
    state = om.create_state("user-1", None, "gmail", "https://app/cb")
    with pytest.raises(ValueError):
        om.decode_state(state + "x", "gmail")


def test_gmail_authorize_url_requests_offline_access():
    url = om.build_authorize_url("gmail", "the-state", "https://app/cb")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=google-client-id" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "gmail.send" in url and "gmail.modify" in url
    assert "state=the-state" in url


def test_microsoft_authorize_url_uses_tenant():
    url = om.build_authorize_url("microsoft", "s", "https://app/cb")
    assert "login.microsoftonline.com/common/oauth2/v2.0/authorize" in url
    assert "Mail.Send" in url and "offline_access" in url


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        om.build_authorize_url("yahoo", "s", "https://app/cb")


# ---------------------------------------------------------------------------
# Code exchange + refresh
# ---------------------------------------------------------------------------

def test_exchange_code_builds_blob(monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured.update({"url": url, "data": data})
        resp = MagicMock(ok=True)
        resp.json.return_value = {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 3599}
        return resp

    monkeypatch.setattr(om.requests, "post", fake_post)
    blob = om.exchange_code("gmail", "the-code", "https://app/cb")

    assert captured["url"] == "https://oauth2.googleapis.com/token"
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code"] == "the-code"
    assert blob["access_token"] == "at-new"
    assert blob["refresh_token"] == "rt-new"


def test_exchange_without_refresh_token_fails(monkeypatch):
    resp = MagicMock(ok=True)
    resp.json.return_value = {"access_token": "at", "expires_in": 3600}
    monkeypatch.setattr(om.requests, "post", lambda *a, **k: resp)
    with pytest.raises(RuntimeError, match="refresh token"):
        om.exchange_code("gmail", "code", "https://app/cb")


def test_get_access_token_reuses_fresh_token(test_db, monkeypatch):
    mailbox = _oauth_mailbox(test_db)

    def _boom(*a, **k):
        raise AssertionError("must not refresh a fresh token")

    monkeypatch.setattr(om, "_token_request", _boom)
    assert om.get_access_token(test_db, mailbox) == "at-1"


def test_get_access_token_refreshes_expired_and_persists(test_db, monkeypatch):
    mailbox = _oauth_mailbox(test_db, expires_in_seconds=-100)
    monkeypatch.setattr(
        om, "_token_request",
        lambda provider, data: {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600},
    )

    assert om.get_access_token(test_db, mailbox) == "at-2"

    stored = json.loads(decrypt_secret(mailbox.smtp_password_encrypted))
    assert stored["access_token"] == "at-2"
    assert stored["refresh_token"] == "rt-2"  # Microsoft-style rotation persisted


def test_refresh_keeps_old_refresh_token_when_not_rotated(test_db, monkeypatch):
    mailbox = _oauth_mailbox(test_db, expires_in_seconds=-100)
    monkeypatch.setattr(
        om, "_token_request",
        lambda provider, data: {"access_token": "at-2", "expires_in": 3600},  # Google: no new RT
    )
    om.get_access_token(test_db, mailbox)
    stored = json.loads(decrypt_secret(mailbox.smtp_password_encrypted))
    assert stored["refresh_token"] == "rt-1"


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def test_send_mime_gmail(test_db, monkeypatch):
    mailbox = _oauth_mailbox(test_db, provider="gmail_oauth")
    captured = {}

    def fake_post(url, headers=None, json=None, data=None, timeout=None):
        captured.update({"url": url, "json": json})
        return MagicMock(ok=True)

    monkeypatch.setattr(om.requests, "post", fake_post)
    om.send_mime(test_db, mailbox, b"MIME-BYTES")

    assert captured["url"].endswith("/gmail/v1/users/me/messages/send")
    import base64
    assert base64.urlsafe_b64decode(captured["json"]["raw"]) == b"MIME-BYTES"


def test_send_mime_microsoft(test_db, monkeypatch):
    mailbox = _oauth_mailbox(test_db, provider="microsoft_oauth")
    captured = {}

    def fake_post(url, headers=None, json=None, data=None, timeout=None):
        captured.update({"url": url, "data": data, "headers": headers})
        return MagicMock(ok=True)

    monkeypatch.setattr(om.requests, "post", fake_post)
    om.send_mime(test_db, mailbox, b"MIME-BYTES")

    assert captured["url"].endswith("/me/sendMail")
    assert captured["headers"]["Content-Type"] == "text/plain"
    import base64
    assert base64.b64decode(captured["data"]) == b"MIME-BYTES"


def test_send_mime_error_raises(test_db, monkeypatch):
    mailbox = _oauth_mailbox(test_db, provider="gmail_oauth")
    resp = MagicMock(ok=False, status_code=403, text="insufficient scope")
    monkeypatch.setattr(om.requests, "post", lambda *a, **k: resp)
    with pytest.raises(RuntimeError, match="403"):
        om.send_mime(test_db, mailbox, b"x")


def test_send_via_mailbox_routes_oauth_to_api(test_db):
    from app.services.mailbox_service import send_via_mailbox

    mailbox = _oauth_mailbox(test_db, provider="gmail_oauth")
    lead = Lead(name="Jane", email="jane@acme.io", company="Acme")
    test_db.add(lead)
    test_db.commit()
    email = OutreachEmail(lead_id=lead.id, step_number=1, subject="s", body="b", status="scheduled")
    test_db.add(email)
    test_db.commit()

    with patch("app.services.oauth_mailbox.send_mime") as mock_send, \
         patch("smtplib.SMTP_SSL") as mock_smtp:
        result = send_via_mailbox(test_db, mailbox, email, "jane@acme.io")

    assert result == "sent"
    mock_send.assert_called_once()
    mock_smtp.assert_not_called()
    test_db.refresh(email)
    assert email.status == "sent"
    assert email.mailbox_id == mailbox.id


def test_auto_mode_sends_step1_via_oauth_pool_without_global_smtp(test_db):
    """An org whose only sending identity is an OAuth mailbox must still get
    the immediate step-1 send in auto mode (no global SMTP_HOST configured)."""
    from app.agents.outreach_agent import OutreachAgent

    _oauth_mailbox(test_db, provider="gmail_oauth")
    lead = Lead(name="Jane", email="jane@acme.io", company="Acme")
    test_db.add(lead)
    test_db.commit()

    agent = OutreachAgent.__new__(OutreachAgent)
    agent._ai = None
    agent._judge = None
    fake_quality = {"overall_score": 0.9, "issues": [], "improvement_hint": ""}
    with patch.object(OutreachAgent, "_personalise_with_judge",
                      return_value=("Subj", "Body", fake_quality)), \
         patch("app.config.settings.SMTP_HOST", ""), \
         patch("app.services.oauth_mailbox.send_mime") as mock_send:
        result = agent.run(test_db, lead.id, {})

    assert result["step1_send"] == "sent"
    mock_send.assert_called_once()
    step1 = test_db.query(OutreachEmail).filter_by(lead_id=lead.id, step_number=1).first()
    assert step1.status == "sent"
    assert step1.mailbox_id is not None


# ---------------------------------------------------------------------------
# Reply polling
# ---------------------------------------------------------------------------

def test_poller_handles_oauth_replies_and_bounces(test_db):
    from app.services.mailbox_service import poll_mailbox_replies

    mailbox = _oauth_mailbox(test_db, provider="gmail_oauth")
    lead = Lead(name="Jane", email="jane@acme.io", company="Acme")
    gone = Lead(name="Gone", email="gone@acme.io", company="Acme")
    test_db.add_all([lead, gone])
    test_db.commit()
    sent = OutreachEmail(lead_id=gone.id, step_number=1, subject="s", body="b",
                         status="sent", sent_at=utcnow())
    test_db.add(sent)
    test_db.commit()

    inbox = [
        {"id": "m1", "from": "jane@acme.io", "subject": "Re: Quick question",
         "body": "Sounds interesting, tell me more."},
        {"id": "m2", "from": "mailer-daemon@mx.example.com",
         "subject": "Delivery Status Notification (Failure)",
         "body": "Final-Recipient: rfc822; gone@acme.io\nStatus: 5.1.1\n550 user unknown"},
    ]

    acked = []
    with patch("app.services.oauth_mailbox.fetch_unread_messages", return_value=inbox), \
         patch("app.services.oauth_mailbox.mark_message_read",
               side_effect=lambda db, mb, mid: acked.append(mid)), \
         patch("app.services.reply_service.handle_reply") as mock_reply:
        summary = poll_mailbox_replies(test_db)

    assert summary["mailboxes"] == 1
    assert summary["matched"] == 1
    assert summary["bounces"] == 1
    assert acked == ["m1", "m2"]
    mock_reply.assert_called_once()
    assert mock_reply.call_args.kwargs.get("source") == f"oauth:{mailbox.email}"
    test_db.refresh(sent)
    assert sent.status == "bounced"


def test_gmail_body_extraction_walks_parts():
    import base64
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": ""}},
            {"mimeType": "text/plain",
             "body": {"data": base64.urlsafe_b64encode("Yes, let's talk".encode()).decode()}},
        ],
    }
    assert om._gmail_plain_body(payload) == "Yes, let's talk"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def _login_admin(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_start_requires_configuration(client, monkeypatch):
    headers = _login_admin(client)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    r = client.get("/mailboxes/oauth/gmail/start", headers=headers)
    assert r.status_code == 400
    assert "GOOGLE_CLIENT_ID" in r.json()["detail"]


def test_start_returns_authorize_url(client):
    headers = _login_admin(client)
    r = client.get("/mailboxes/oauth/gmail/start",
                   headers=headers, params={"redirect_uri": "https://app/cb"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authorize_url"].startswith("https://accounts.google.com/")
    assert om.decode_state(body["state"], "gmail")["redirect_uri"] == "https://app/cb"


def test_start_rejects_unknown_provider_and_requires_auth(client):
    headers = _login_admin(client)
    assert client.get("/mailboxes/oauth/yahoo/start", headers=headers).status_code == 404
    assert client.get("/mailboxes/oauth/gmail/start").status_code in (401, 403)


def test_callback_rejects_bad_state(client):
    r = client.get("/mailboxes/oauth/gmail/callback", params={"code": "c", "state": "garbage"})
    assert r.status_code == 400


def test_callback_reports_provider_error(client):
    r = client.get("/mailboxes/oauth/gmail/callback", params={"error": "access_denied"})
    assert r.status_code == 400
    assert "access_denied" in r.json()["detail"]


def test_callback_creates_mailbox(client, test_db):
    headers = _login_admin(client)
    state = client.get(
        "/mailboxes/oauth/gmail/start",
        headers=headers, params={"redirect_uri": "https://app/cb"},
    ).json()["state"]

    with patch("app.services.oauth_mailbox.exchange_code", return_value=_token_blob()) as mock_exchange, \
         patch("app.services.oauth_mailbox.fetch_profile_email", return_value="rep@company.com"):
        r = client.get("/mailboxes/oauth/gmail/callback", params={"code": "the-code", "state": state})

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "connected"
    mock_exchange.assert_called_once_with("gmail", "the-code", "https://app/cb")

    mailbox = test_db.query(SendingMailbox).filter_by(email="rep@company.com").first()
    assert mailbox.provider == "gmail_oauth"
    assert mailbox.warmup_started_at is not None
    stored = json.loads(decrypt_secret(mailbox.smtp_password_encrypted))
    assert stored["refresh_token"] == "rt-1"

    # Listing never leaks tokens
    listing = client.get("/mailboxes", headers=headers).json()["mailboxes"]
    assert "rt-1" not in json.dumps(listing) and "at-1" not in json.dumps(listing)


def test_callback_reconnects_existing_mailbox(client, test_db):
    headers = _login_admin(client)
    from app.services.tenancy import get_default_org
    org_id = get_default_org(test_db).id
    existing = _oauth_mailbox(test_db, email="rep@company.com", org_id=org_id)
    existing.is_active = False
    test_db.commit()

    state = client.get(
        "/mailboxes/oauth/gmail/start",
        headers=headers, params={"redirect_uri": "https://app/cb"},
    ).json()["state"]

    new_blob = {**_token_blob(), "refresh_token": "rt-fresh"}
    with patch("app.services.oauth_mailbox.exchange_code", return_value=new_blob), \
         patch("app.services.oauth_mailbox.fetch_profile_email", return_value="rep@company.com"):
        r = client.get("/mailboxes/oauth/gmail/callback", params={"code": "c", "state": state})

    assert r.status_code == 200
    assert test_db.query(SendingMailbox).filter_by(email="rep@company.com").count() == 1
    test_db.refresh(existing)
    assert existing.is_active is True
    assert json.loads(decrypt_secret(existing.smtp_password_encrypted))["refresh_token"] == "rt-fresh"
