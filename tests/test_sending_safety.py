"""
Safety rails for real sending:

  - CAN-SPAM postal address in every commercial email; real sends held without one
  - new orgs default to "approve" (covered in test_approvals)
  - the conversational agent only answers prospects when the org opts in, and
    an email reply it writes is stored as an unsent draft
  - mailboxes on domains with no SPF and no DKIM are kept out of rotation
"""
import email as email_lib
from datetime import datetime
from unittest.mock import patch

import dns.resolver
import pytest

from app.agents.outreach_agent import OutreachAgent, send_pending_scheduled_emails
from app.database.models import Conversation, Lead, OutreachEmail, SendingMailbox
from app.services import sender_auth
from app.services.email_compose import build_message
from app.services.mailbox_service import encrypt_secret, pick_mailbox
from app.services.tenancy import get_default_org, set_org_setting

ADDRESS = "AutonomousSDR Inc., 1 Main St, Springfield, IL 62701"


def _login(client, email="admin@test.com", password="password123"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _admin(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    return _login(client)


def _lead(db, email="jane@acme.com"):
    lead = Lead(name="Jane", email=email, company="Acme", org_id=get_default_org(db).id, status="complete")
    db.add(lead)
    db.commit()
    return lead


def _email(db, lead, status="scheduled"):
    e = OutreachEmail(lead_id=lead.id, step_number=1, subject="Hello", body="Body <b>",
                      status=status, scheduled_at=datetime(2026, 7, 1))
    db.add(e)
    db.commit()
    return e


def _parts(msg) -> dict[str, str]:
    parsed = email_lib.message_from_string(msg.as_string())
    return {p.get_content_type(): p.get_payload(decode=True).decode()
            for p in parsed.walk() if not p.is_multipart()}


# ---------------------------------------------------------------------------
# Postal address
# ---------------------------------------------------------------------------

def test_footer_carries_address_and_unsubscribe(test_db):
    email = _email(test_db, _lead(test_db))
    with patch.multiple("app.config.settings", APP_BASE_URL="https://api.example.com",
                        OUTREACH_POSTAL_ADDRESS="1 Main & Co, Springfield"):
        msg = build_message(test_db, email, "me@us.com", "jane@acme.com", None)
    parts = _parts(msg)
    assert "1 Main & Co, Springfield" in parts["text/plain"]
    assert f"/unsubscribe/{email.id}" in parts["text/plain"]
    assert "1 Main &amp; Co, Springfield" in parts["text/html"]
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_org_address_overrides_env(test_db):
    org = get_default_org(test_db).id
    set_org_setting(test_db, org, "postal_address", ADDRESS)
    email = _email(test_db, _lead(test_db))
    with patch("app.config.settings.OUTREACH_POSTAL_ADDRESS", "env fallback"):
        assert ADDRESS in _parts(build_message(test_db, email, "me@us.com", "x@y.com", org))["text/plain"]


def test_real_send_held_without_address(test_db):
    lead = _lead(test_db)
    email = _email(test_db, lead)
    with patch.multiple("app.config.settings", SMTP_HOST="smtp.example.com", OUTREACH_POSTAL_ADDRESS=""), \
         patch("app.services.mailbox_service.pick_mailbox", return_value=None), \
         patch("app.agents.outreach_agent.smtplib.SMTP_SSL") as smtp:
        result = OutreachAgent()._send_email(test_db, email, lead.email)
    assert result.startswith("held:")
    smtp.assert_not_called()
    test_db.refresh(email)
    assert email.status == "scheduled"


def test_scheduler_counts_held_as_skipped(test_db):
    lead = _lead(test_db)
    lead.timezone = "Asia/Tokyo"
    test_db.commit()
    _email(test_db, lead)
    with patch.multiple("app.config.settings", SMTP_HOST="smtp.example.com", OUTREACH_POSTAL_ADDRESS="",
                        OUTREACH_SEND_WINDOW_START=0, OUTREACH_SEND_WINDOW_END=24,
                        OUTREACH_WEEKDAYS_ONLY=False), \
         patch("app.services.mailbox_service.pick_mailbox", return_value=None):
        summary = send_pending_scheduled_emails(test_db)
    assert summary["sent"] == 0 and summary["failed"] == 0 and summary["skipped"] == 1


def test_guardrails_report_missing_address(client):
    headers = _admin(client)
    with patch("app.config.settings.OUTREACH_POSTAL_ADDRESS", ""):
        body = client.get("/outreach/guardrails", headers=headers).json()
    assert body["can_send"] is False
    assert body["postal_address_configured"] is False
    assert "postal address" in body["reason"]


def test_sending_settings_roundtrip(client):
    headers = _admin(client)
    assert client.get("/outreach/sending-settings", headers=headers).json()["auto_reply_enabled"] is False

    r = client.put("/outreach/sending-settings", headers=headers,
                   json={"postal_address": ADDRESS, "auto_reply_enabled": True})
    assert r.status_code == 200
    assert r.json() == {"postal_address": ADDRESS, "auto_reply_enabled": True}

    assert client.put("/outreach/sending-settings", headers=headers,
                      json={"auto_reply_enabled": "yes"}).status_code == 422
    assert client.put("/outreach/sending-settings", headers=headers,
                      json={"postal_address": "x" * 301}).status_code == 422


def test_reps_cannot_change_sending_settings(client, test_session_factory):
    from app.database.models import User
    from app.services.auth_service import hash_password
    _admin(client)
    db = test_session_factory()
    db.add(User(email="rep@test.com", password_hash=hash_password("password123"), role="rep",
                org_id=get_default_org(db).id))
    db.commit()
    db.close()
    r = client.put("/outreach/sending-settings", headers=_login(client, "rep@test.com"),
                   json={"auto_reply_enabled": True})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Auto-reply
# ---------------------------------------------------------------------------

def _reply(client, lead_id, text):
    return client.post("/ingest/email-reply", json={"lead_id": lead_id, "reply_text": text})


def test_reply_goes_to_a_human_by_default(client, test_session_factory):
    db = test_session_factory()
    lead_id = _lead(db).id
    db.close()

    with patch("app.services.reply_service.generate_agent_response") as agent:
        r = _reply(client, lead_id, "Interesting — can you send pricing?")
    assert r.status_code == 202
    assert "human" in r.json()["message"]
    agent.assert_not_called()

    db = test_session_factory()
    conv = db.query(Conversation).filter_by(lead_id=lead_id).one()
    assert conv.needs_human is True
    db.close()


def test_opted_in_org_gets_agent_draft(client, test_session_factory):
    db = test_session_factory()
    lead_id = _lead(db).id
    set_org_setting(db, get_default_org(db).id, "auto_reply_enabled", True)
    db.close()

    with patch("app.services.reply_service.generate_agent_response") as agent:
        r = _reply(client, lead_id, "Interesting — can you send pricing?")
    assert r.status_code == 202
    agent.assert_called_once()


def test_follow_up_replies_land_in_the_thread(client, test_session_factory):
    db = test_session_factory()
    lead_id = _lead(db).id
    db.close()
    _reply(client, lead_id, "First question about pricing")
    _reply(client, lead_id, "And a second one about onboarding")

    db = test_session_factory()
    conv = db.query(Conversation).filter_by(lead_id=lead_id).one()
    assert [m["content"] for m in conv.messages] == [
        "First question about pricing", "And a second one about onboarding",
    ]
    db.close()


def test_agent_email_reply_is_marked_unsent_and_not_duplicated(test_db):
    from app.agents.conversational_agent import ConversationalAgent
    from app.services.reply_service import handle_reply

    lead = _lead(test_db)
    handle_reply(test_db, lead, "Can you send pricing?")

    agent = ConversationalAgent()
    with patch.object(agent._objection_handler, "classify",
                      return_value={"needs_human": False, "sentiment": "positive",
                                    "objection_type": None, "strategy": ""}), \
         patch.object(agent, "_generate_reply", return_value="Sure — here it is."):
        agent.run(test_db, lead.id, {"channel": "email", "mode": "reply", "message": "Can you send pricing?"})

    conv = test_db.query(Conversation).filter_by(lead_id=lead.id).one()
    assert [(m["role"], m.get("delivered")) for m in conv.messages] == [("lead", None), ("agent", False)]


# ---------------------------------------------------------------------------
# SPF / DKIM / DMARC
# ---------------------------------------------------------------------------

class FakeResolver:
    def __init__(self, records: dict[str, list[str]], fail: bool = False):
        self.records, self.fail = records, fail

    def resolve(self, name, rtype):
        if self.fail:
            raise dns.exception.Timeout()
        if name not in self.records:
            raise dns.resolver.NXDOMAIN()
        return [type("R", (), {"strings": [r.encode()]})() for r in self.records[name]]


GOOD = {
    "acme.com": ["v=spf1 include:_spf.google.com ~all"],
    "_dmarc.acme.com": ["v=DMARC1; p=quarantine; rua=mailto:d@acme.com"],
    "google._domainkey.acme.com": ["v=DKIM1; k=rsa; p=MIIBIjANBg"],
}


def test_fully_authenticated_domain():
    result = sender_auth.check_domain("acme.com", resolver=FakeResolver(GOOD))
    assert result["spf"]["ok"] and result["dmarc"]["ok"] and result["dkim"]["ok"]
    assert result["dkim"]["selector"] == "google"
    assert result["dmarc"]["policy"] == "quarantine"
    assert result["can_send"] is True and result["issues"] == []


def test_no_spf_no_dkim_blocks():
    result = sender_auth.check_domain("acme.com", resolver=FakeResolver({}))
    assert result["can_send"] is False
    assert any("SPF" in issue for issue in result["issues"])


def test_dkim_alone_is_enough_but_dmarc_is_flagged():
    records = {"selector1._domainkey.acme.com": ["v=DKIM1; p=abc"]}
    result = sender_auth.check_domain("acme.com", resolver=FakeResolver(records))
    assert result["can_send"] is True
    assert any("DMARC" in issue for issue in result["issues"])


def test_dns_outage_never_blocks():
    result = sender_auth.check_domain("acme.com", resolver=FakeResolver({}, fail=True))
    assert result["spf"]["ok"] is None and result["can_send"] is True


def _smtp_mailbox(db, email):
    box = SendingMailbox(email=email, smtp_host="smtp.x", smtp_username=email,
                         smtp_password_encrypted=encrypt_secret("pw"), org_id=None)
    db.add(box)
    db.commit()
    return box


def test_rotation_skips_unauthenticated_domain(test_db):
    bad = _smtp_mailbox(test_db, "rep@nospf.com")
    good = _smtp_mailbox(test_db, "rep@acme.com")
    resolver = FakeResolver(GOOD)
    with patch("app.config.settings.SENDER_AUTH_CHECK_ENABLED", True), \
         patch.object(sender_auth, "_make_resolver", return_value=resolver):
        picked = pick_mailbox(test_db, None)
    assert picked.id == good.id
    test_db.refresh(bad)
    assert bad.dns_auth["can_send"] is False


@pytest.mark.parametrize("enabled", [True, False])
def test_mailbox_create_reports_dns(client, enabled):
    headers = _admin(client)
    with patch("app.config.settings.SENDER_AUTH_CHECK_ENABLED", enabled), \
         patch.object(sender_auth, "_make_resolver", return_value=FakeResolver(GOOD)):
        r = client.post("/mailboxes", headers=headers, json={
            "email": "rep@acme.com", "smtp_host": "smtp.acme.com",
            "smtp_username": "rep@acme.com", "smtp_password": "pw",
        })
    assert r.status_code == 201, r.text
    dns_auth = r.json()["dns_auth"]
    assert (dns_auth["can_send"] is True) if enabled else dns_auth is None
