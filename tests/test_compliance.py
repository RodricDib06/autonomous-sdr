"""
Tests for the compliance & deliverability service.

Coverage:
  - suppression list: add (idempotent, kind detection), match (email/domain), remove
  - unsubscribe-intent detection on reply text
  - sequence cancellation on reply / unsubscribe
  - process_unsubscribe end-to-end (suppress + cancel + tag)
  - send guardrails: quiet hours, weekends, daily cap
  - send_pending_scheduled_emails: guardrail hold, reply-stop, suppression-stop,
    demo-mode sends counted as sent
  - /unsubscribe/{email_id} public endpoint
  - /suppressions CRUD endpoints + RBAC
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.database.models import Lead, OutreachEmail, SuppressionEntry
from app.services.compliance import (
    add_suppression,
    can_send_now,
    cancel_scheduled_emails,
    detect_unsubscribe_intent,
    domain_of,
    is_suppressed,
    lead_has_replied,
    normalise,
    process_unsubscribe,
    remove_suppression,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(db, email="jane@acme.com", **kwargs):
    lead = Lead(name="Jane Doe", email=email, company="Acme", **kwargs)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _make_email(db, lead, status="scheduled", step=2, scheduled_at=None, sent_at=None):
    email = OutreachEmail(
        lead_id=lead.id,
        step_number=step,
        subject="s",
        body="b",
        status=status,
        scheduled_at=scheduled_at or datetime.utcnow() - timedelta(minutes=5),
        sent_at=sent_at,
    )
    db.add(email)
    db.commit()
    db.refresh(email)
    return email


ALLOW_ALL = {
    "OUTREACH_WEEKDAYS_ONLY": False,
    "OUTREACH_SEND_WINDOW_START": 0,
    "OUTREACH_SEND_WINDOW_END": 24,
    "OUTREACH_DAILY_SEND_LIMIT": 200,
}


def _patch_settings(**overrides):
    from app.config import settings
    values = {**ALLOW_ALL, **overrides}
    return patch.multiple(settings, **values)


# ---------------------------------------------------------------------------
# Normalisation & matching
# ---------------------------------------------------------------------------

def test_normalise_and_domain():
    assert normalise("  Jane@ACME.com ") == "jane@acme.com"
    assert domain_of("Jane@ACME.com") == "acme.com"
    assert domain_of("acme.com") == "acme.com"


def test_add_suppression_detects_kind(test_db):
    email_entry = add_suppression(test_db, "Jane@Acme.com")
    domain_entry = add_suppression(test_db, "spam.io")
    assert email_entry.kind == "email"
    assert email_entry.value == "jane@acme.com"
    assert domain_entry.kind == "domain"


def test_add_suppression_idempotent(test_db):
    first = add_suppression(test_db, "jane@acme.com")
    second = add_suppression(test_db, "JANE@acme.com")
    assert first.id == second.id
    assert test_db.query(SuppressionEntry).count() == 1


def test_is_suppressed_exact_email(test_db):
    add_suppression(test_db, "jane@acme.com")
    assert is_suppressed(test_db, "Jane@Acme.com") is not None
    assert is_suppressed(test_db, "other@acme.com") is None


def test_is_suppressed_by_domain(test_db):
    add_suppression(test_db, "acme.com")
    assert is_suppressed(test_db, "anyone@acme.com") is not None
    assert is_suppressed(test_db, "anyone@other.com") is None


def test_remove_suppression(test_db):
    entry = add_suppression(test_db, "jane@acme.com")
    assert remove_suppression(test_db, entry.id) is True
    assert remove_suppression(test_db, entry.id) is False
    assert is_suppressed(test_db, "jane@acme.com") is None


# ---------------------------------------------------------------------------
# Unsubscribe-intent detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Please unsubscribe me from this list",
    "UNSUBSCRIBE",
    "remove me from your list",
    "Take me off this list please",
    "stop emailing me",
    "Do not contact me again",
    "don't email me",
    "opt me out",
    "STOP",
])
def test_unsubscribe_intent_positive(text):
    assert detect_unsubscribe_intent(text) is True


@pytest.mark.parametrize("text", [
    "Thanks, I'd love to learn more about pricing",
    "Can we stop by your booth at the conference?",
    "We can't stop growing — need help scaling the team",
    "",
    None,
])
def test_unsubscribe_intent_negative(text):
    assert detect_unsubscribe_intent(text) is False


# ---------------------------------------------------------------------------
# Sequence cancellation
# ---------------------------------------------------------------------------

def test_cancel_scheduled_emails_only_touches_scheduled(test_db):
    lead = _make_lead(test_db)
    _make_email(test_db, lead, status="scheduled", step=2)
    _make_email(test_db, lead, status="scheduled", step=3)
    sent = _make_email(test_db, lead, status="sent", step=1)

    cancelled = cancel_scheduled_emails(test_db, lead.id, "test reason")
    assert cancelled == 2

    statuses = [e.status for e in test_db.query(OutreachEmail).filter_by(lead_id=lead.id)]
    assert statuses.count("cancelled") == 2
    test_db.refresh(sent)
    assert sent.status == "sent"


def test_lead_has_replied(test_db):
    lead = _make_lead(test_db)
    assert lead_has_replied(test_db, lead.id) is False
    _make_email(test_db, lead, status="replied", step=1)
    assert lead_has_replied(test_db, lead.id) is True


def test_process_unsubscribe_full_flow(test_db):
    lead = _make_lead(test_db)
    _make_email(test_db, lead, status="scheduled", step=2)

    result = process_unsubscribe(test_db, lead, source="reply_keyword")

    assert result["cancelled_emails"] == 1
    assert is_suppressed(test_db, lead.email) is not None
    test_db.refresh(lead)
    assert "unsubscribed" in (lead.tags or [])


# ---------------------------------------------------------------------------
# Send guardrails
# ---------------------------------------------------------------------------

def test_can_send_blocks_weekend(test_db):
    with _patch_settings(OUTREACH_WEEKDAYS_ONLY=True):
        saturday = datetime(2026, 7, 4, 10, 0)  # a Saturday
        allowed, reason = can_send_now(test_db, saturday)
    assert allowed is False
    assert "weekend" in reason.lower()


def test_can_send_blocks_outside_window(test_db):
    with _patch_settings(OUTREACH_SEND_WINDOW_START=8, OUTREACH_SEND_WINDOW_END=18):
        night = datetime(2026, 7, 1, 3, 0)  # 3 a.m. Wednesday
        allowed, reason = can_send_now(test_db, night)
    assert allowed is False
    assert "window" in reason.lower()


def test_can_send_blocks_at_daily_cap(test_db):
    lead = _make_lead(test_db)
    for _ in range(3):
        _make_email(test_db, lead, status="sent", sent_at=datetime.utcnow())
    with _patch_settings(OUTREACH_DAILY_SEND_LIMIT=3):
        allowed, reason = can_send_now(test_db, datetime(2026, 7, 1, 10, 0))
    assert allowed is False
    assert "cap" in reason.lower()


def test_can_send_ok_inside_window(test_db):
    with _patch_settings():
        allowed, reason = can_send_now(test_db, datetime(2026, 7, 1, 10, 0))
    assert allowed is True


def test_old_sends_do_not_count_toward_cap(test_db):
    lead = _make_lead(test_db)
    _make_email(test_db, lead, status="sent", sent_at=datetime.utcnow() - timedelta(days=2))
    with _patch_settings(OUTREACH_DAILY_SEND_LIMIT=1):
        allowed, _ = can_send_now(test_db, datetime(2026, 7, 1, 10, 0))
    assert allowed is True


# ---------------------------------------------------------------------------
# Scheduled sender integration
# ---------------------------------------------------------------------------

def test_scheduled_sender_holds_outside_window(test_db):
    from app.agents.outreach_agent import send_pending_scheduled_emails

    lead = _make_lead(test_db)  # .com address -> no timezone -> global UTC window
    _make_email(test_db, lead, status="scheduled")

    # start == end makes the window empty, so the recipient gate always holds
    with _patch_settings(OUTREACH_SEND_WINDOW_START=0, OUTREACH_SEND_WINDOW_END=0, SMTP_HOST=""):
        summary = send_pending_scheduled_emails(test_db)

    assert summary["sent"] == 0
    assert summary["skipped"] == 1
    # Email untouched — stays scheduled for a tick inside the window
    assert test_db.query(OutreachEmail).filter_by(status="scheduled").count() == 1


def test_scheduled_sender_stops_sequence_after_reply(test_db):
    from app.agents.outreach_agent import send_pending_scheduled_emails

    lead = _make_lead(test_db)
    _make_email(test_db, lead, status="replied", step=1)
    _make_email(test_db, lead, status="scheduled", step=2)

    with _patch_settings():
        summary = send_pending_scheduled_emails(test_db)

    assert summary["sent"] == 0
    assert summary["cancelled"] == 1
    assert test_db.query(OutreachEmail).filter_by(status="cancelled").count() == 1


def test_scheduled_sender_skips_suppressed_lead(test_db):
    from app.agents.outreach_agent import send_pending_scheduled_emails

    lead = _make_lead(test_db)
    _make_email(test_db, lead, status="scheduled", step=2)
    add_suppression(test_db, lead.email, source="manual")

    with _patch_settings():
        summary = send_pending_scheduled_emails(test_db)

    assert summary["sent"] == 0
    assert summary["cancelled"] == 1


def test_scheduled_sender_counts_demo_sends_as_sent(test_db):
    from app.agents.outreach_agent import send_pending_scheduled_emails

    lead = _make_lead(test_db)
    _make_email(test_db, lead, status="scheduled", step=2)

    # No SMTP host → demo mode: _send_email returns "sent_demo"
    with _patch_settings(SMTP_HOST=""):
        summary = send_pending_scheduled_emails(test_db)

    assert summary["sent"] == 1
    assert summary["failed"] == 0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _admin_headers(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_unsubscribe_endpoint_full_flow(client, test_session_factory):
    db = test_session_factory()
    lead = _make_lead(db, email="optout@corp.com")
    email = _make_email(db, lead, status="sent", step=1)
    _make_email(db, lead, status="scheduled", step=2)
    email_id = email.id
    db.close()

    r = client.get(f"/unsubscribe/{email_id}")
    assert r.status_code == 200
    assert "unsubscribed" in r.text.lower()

    db = test_session_factory()
    assert is_suppressed(db, "optout@corp.com") is not None
    assert db.query(OutreachEmail).filter_by(status="cancelled").count() == 1
    db.close()


def test_unsubscribe_endpoint_unknown_id(client):
    r = client.get("/unsubscribe/not-a-real-id")
    assert r.status_code == 404


def test_suppressions_crud(client):
    headers = _admin_headers(client)

    r = client.post("/suppressions", json={"value": "Spam@Corp.com", "reason": "asked"}, headers=headers)
    assert r.status_code == 201
    entry_id = r.json()["id"]
    assert r.json()["value"] == "spam@corp.com"
    assert r.json()["kind"] == "email"

    r = client.get("/suppressions", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = client.delete(f"/suppressions/{entry_id}", headers=headers)
    assert r.status_code == 200

    r = client.get("/suppressions", headers=headers)
    assert r.json()["total"] == 0


def test_suppressions_rejects_invalid_value(client):
    headers = _admin_headers(client)
    r = client.post("/suppressions", json={"value": "not-an-email"}, headers=headers)
    assert r.status_code == 422


def test_suppressions_require_auth(client):
    assert client.get("/suppressions").status_code in (401, 403)
    assert client.post("/suppressions", json={"value": "x@y.com"}).status_code in (401, 403)


def test_guardrails_endpoint(client):
    headers = _admin_headers(client)
    r = client.get("/outreach/guardrails", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert {"can_send", "reason", "sent_last_24h", "daily_limit", "suppression_count"} <= set(body)


def test_email_reply_with_unsubscribe_intent(client, test_session_factory):
    db = test_session_factory()
    lead = _make_lead(db, email="done@corp.com")
    _make_email(db, lead, status="scheduled", step=2)
    lead_id = lead.id
    db.close()

    r = client.post("/ingest/email-reply", json={
        "lead_id": lead_id,
        "reply_text": "Please remove me from your list",
    })
    assert r.status_code == 202
    assert r.json()["status"] == "unsubscribed"

    db = test_session_factory()
    assert is_suppressed(db, "done@corp.com") is not None
    assert db.query(OutreachEmail).filter_by(status="cancelled").count() == 1
    db.close()
