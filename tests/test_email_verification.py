"""
Tests for email verification (pre-send gate) and bounce handling.

Coverage:
  - verify_email check chain: syntax, disposable, role account, MX outcomes
    (present / NXDOMAIN / null MX / DNS failure), optional SMTP probe
  - verify_lead_email: persistence, TTL reuse, disabled flag
  - outreach agent skips undeliverable leads; scheduler cancels their cadence
  - bounce classification, DSN parsing (structured + unstructured), and the
    full hard-bounce loop: mark bounced → suppress → cancel → undeliverable
  - IMAP poller routes DSNs to the bounce handler, not the reply pipeline
  - on-demand verification endpoint
"""

from datetime import timedelta
from email.message import EmailMessage, Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import patch

from app.database.models import Lead, OutreachEmail, SuppressionEntry
from app.services import email_verification as ev
from app.services.bounce_service import handle_bounce, looks_like_bounce, parse_bounce
from app.utils.time import utcnow


def _mx_ok(domain):
    return (True, "1 MX record(s)", [f"mx.{domain}"])


# ---------------------------------------------------------------------------
# verify_email
# ---------------------------------------------------------------------------

def test_bad_syntax_is_undeliverable():
    result = ev.verify_email("not-an-email")
    assert result.status == "undeliverable"
    assert result.checks["syntax"]["ok"] is False


def test_disposable_domain_is_undeliverable():
    result = ev.verify_email("someone@mailinator.com")
    assert result.status == "undeliverable"
    assert "disposable" in result.reason.lower()


def test_valid_address_with_mx(monkeypatch):
    monkeypatch.setattr(ev, "_resolve_mx_cached", lambda d: _mx_ok(d))
    result = ev.verify_email("jane@acme.io", smtp_probe=False)
    assert result.status == "valid"
    assert result.checks["mx"]["ok"] is True


def test_role_account_is_risky_not_blocked(monkeypatch):
    monkeypatch.setattr(ev, "_resolve_mx_cached", lambda d: _mx_ok(d))
    result = ev.verify_email("info@acme.io", smtp_probe=False)
    assert result.status == "risky"


def test_nxdomain_is_undeliverable(monkeypatch):
    monkeypatch.setattr(ev, "_resolve_mx_cached", lambda d: (False, "Domain does not exist (NXDOMAIN)", []))
    result = ev.verify_email("jane@no-such-domain-xyz.io", smtp_probe=False)
    assert result.status == "undeliverable"


def test_dns_failure_is_unknown_never_blocks(monkeypatch):
    monkeypatch.setattr(ev, "_resolve_mx_cached", lambda d: (None, "DNS lookup failed: timeout", []))
    result = ev.verify_email("jane@acme.io", smtp_probe=False)
    assert result.status == "unknown"


def test_smtp_probe_rejection_is_undeliverable(monkeypatch):
    monkeypatch.setattr(ev, "_resolve_mx_cached", lambda d: _mx_ok(d))
    monkeypatch.setattr(ev, "_smtp_probe", lambda email, mx: (False, "RCPT rejected (550: user unknown)"))
    result = ev.verify_email("gone@acme.io", smtp_probe=True)
    assert result.status == "undeliverable"


def test_smtp_probe_inconclusive_stays_valid(monkeypatch):
    monkeypatch.setattr(ev, "_resolve_mx_cached", lambda d: _mx_ok(d))
    monkeypatch.setattr(ev, "_smtp_probe", lambda email, mx: (None, "greylisted"))
    result = ev.verify_email("jane@acme.io", smtp_probe=True)
    assert result.status == "valid"


def test_null_mx_detection(monkeypatch):
    class FakeRecord:
        preference = 0
        exchange = "."

    class FakeResolver:
        timeout = lifetime = 5

        def resolve(self, domain, rrtype):
            assert rrtype == "MX"
            return [FakeRecord()]

    import dns.resolver
    monkeypatch.setattr(dns.resolver, "Resolver", FakeResolver)
    has_mx, detail, hosts = ev._resolve_mx("nullmx.example")
    assert has_mx is False
    assert "null MX" in detail


# ---------------------------------------------------------------------------
# verify_lead_email persistence + TTL
# ---------------------------------------------------------------------------

def _make_lead(db, email="jane@acme.io", **kwargs):
    lead = Lead(name="Jane", email=email, company="Acme", **kwargs)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def test_verify_lead_email_persists(test_db, monkeypatch):
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFICATION_ENABLED", True)
    monkeypatch.setattr(ev, "_resolve_mx_cached", lambda d: _mx_ok(d))
    lead = _make_lead(test_db)

    status = ev.verify_lead_email(test_db, lead)

    assert status == "valid"
    assert lead.email_verification_status == "valid"
    assert lead.email_verified_at is not None
    assert lead.email_verification_detail["checks"]["mx"]["ok"] is True


def test_verify_lead_email_reuses_fresh_result(test_db, monkeypatch):
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFICATION_ENABLED", True)
    lead = _make_lead(test_db)
    lead.email_verification_status = "valid"
    lead.email_verified_at = utcnow() - timedelta(days=1)
    test_db.commit()

    def _boom(_):
        raise AssertionError("DNS must not be hit inside the TTL")

    monkeypatch.setattr(ev, "_resolve_mx_cached", _boom)
    assert ev.verify_lead_email(test_db, lead) == "valid"


def test_verify_lead_email_reverifies_after_ttl(test_db, monkeypatch):
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFICATION_ENABLED", True)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFICATION_TTL_DAYS", 7)
    monkeypatch.setattr(ev, "_resolve_mx_cached", lambda d: (False, "NXDOMAIN", []))
    lead = _make_lead(test_db)
    lead.email_verification_status = "valid"
    lead.email_verified_at = utcnow() - timedelta(days=30)
    test_db.commit()

    assert ev.verify_lead_email(test_db, lead) == "undeliverable"


def test_verify_lead_email_disabled_is_noop(test_db, monkeypatch):
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFICATION_ENABLED", False)
    lead = _make_lead(test_db)
    assert ev.verify_lead_email(test_db, lead) == "unknown"
    assert lead.email_verification_status is None


# ---------------------------------------------------------------------------
# Outreach integration
# ---------------------------------------------------------------------------

def test_outreach_agent_skips_undeliverable_lead(test_db, monkeypatch):
    from app.agents.outreach_agent import OutreachAgent

    monkeypatch.setattr(ev.settings, "EMAIL_VERIFICATION_ENABLED", True)
    monkeypatch.setattr(ev, "_resolve_mx_cached", lambda d: (False, "NXDOMAIN", []))
    lead = _make_lead(test_db, email="gone@dead-domain.io")

    agent = OutreachAgent.__new__(OutreachAgent)
    agent._ai = None
    agent._judge = None
    result = agent.run(test_db, lead.id, {})

    assert result == {"status": "skipped", "reason": "email_undeliverable",
                      "verification_status": "undeliverable"}
    assert test_db.query(OutreachEmail).filter_by(lead_id=lead.id).count() == 0


def test_scheduler_cancels_cadence_for_undeliverable(test_db):
    from app.agents.outreach_agent import send_pending_scheduled_emails

    lead = _make_lead(test_db)
    lead.email_verification_status = "undeliverable"
    email = OutreachEmail(
        lead_id=lead.id, step_number=2, subject="s", body="b",
        status="scheduled", scheduled_at=utcnow() - timedelta(hours=1),
    )
    test_db.add(email)
    test_db.commit()

    with patch("app.services.compliance.can_send_to_recipient", return_value=(True, "ok")):
        result = send_pending_scheduled_emails(test_db)

    test_db.refresh(email)
    assert email.status == "cancelled"
    assert result["cancelled"] == 1
    assert result["sent"] == 0


# ---------------------------------------------------------------------------
# Bounce classification + parsing
# ---------------------------------------------------------------------------

def test_looks_like_bounce_signals():
    assert looks_like_bounce("MAILER-DAEMON@googlemail.com", "any")
    assert looks_like_bounce("postmaster@outlook.com", "any")
    assert looks_like_bounce("x@y.com", "Undeliverable: Quick question")
    assert looks_like_bounce("x@y.com", "Mail delivery failed: returning message")
    assert looks_like_bounce("x@y.com", "any", content_type="multipart/report")
    assert not looks_like_bounce("jane@acme.io", "Re: Quick question about Acme")


def _dsn_message(recipient="gone@acme.io", status="5.1.1"):
    """Structured RFC 3464 DSN with a message/delivery-status part."""
    msg = MIMEMultipart("report", **{"report-type": "delivery-status"})
    msg["From"] = "Mail Delivery Subsystem <mailer-daemon@mx.example.com>"
    msg["Subject"] = "Delivery Status Notification (Failure)"
    msg.attach(MIMEText("Your message could not be delivered.", "plain"))

    dsn = Message()
    dsn["Content-Type"] = "message/delivery-status"
    per_message = Message()
    per_message["Reporting-MTA"] = "dns; mx.example.com"
    per_recipient = Message()
    per_recipient["Final-Recipient"] = f"rfc822; {recipient}"
    per_recipient["Action"] = "failed"
    per_recipient["Status"] = status
    per_recipient["Diagnostic-Code"] = "smtp; 550 5.1.1 User unknown"
    dsn.set_payload([per_message, per_recipient])  # RFC 3464 header blocks
    msg.attach(dsn)
    return msg


def test_parse_structured_hard_bounce():
    bounce = parse_bounce(_dsn_message(status="5.1.1"))
    assert bounce == {
        "recipient": "gone@acme.io",
        "hard": True,
        "diagnostic": bounce["diagnostic"],
    }
    assert "5.1.1" in bounce["diagnostic"]


def test_parse_structured_soft_bounce():
    bounce = parse_bounce(_dsn_message(status="4.2.2"))
    assert bounce["hard"] is False


def test_parse_unstructured_bounce_falls_back_to_body():
    msg = EmailMessage()
    msg["From"] = "MAILER-DAEMON@mx.example.com"
    msg["Subject"] = "Mail delivery failed"
    body = "Delivery to the following recipient failed permanently:\n\n  gone@acme.io\n\n550 No such user"
    msg.set_content(body)
    bounce = parse_bounce(msg, body)
    assert bounce["recipient"] == "gone@acme.io"
    assert bounce["hard"] is True


def test_parse_returns_none_without_recipient():
    msg = EmailMessage()
    msg["From"] = "mailer-daemon@mx.example.com"
    msg.set_content("Something went wrong.")
    assert parse_bounce(msg, "Something went wrong.") is None


# ---------------------------------------------------------------------------
# handle_bounce
# ---------------------------------------------------------------------------

def test_hard_bounce_full_loop(test_db):
    lead = _make_lead(test_db, email="gone@acme.io")
    sent = OutreachEmail(
        lead_id=lead.id, step_number=1, subject="s", body="b",
        status="sent", sent_at=utcnow(),
    )
    followup = OutreachEmail(
        lead_id=lead.id, step_number=2, subject="s2", body="b2",
        status="scheduled", scheduled_at=utcnow() + timedelta(days=3),
    )
    test_db.add_all([sent, followup])
    test_db.commit()

    result = handle_bounce(test_db, "gone@acme.io", hard=True, diagnostic="550 5.1.1 User unknown")

    test_db.refresh(sent)
    test_db.refresh(followup)
    test_db.refresh(lead)
    assert result["status"] == "hard_bounce"
    assert sent.status == "bounced"
    assert followup.status == "cancelled"
    assert lead.email_verification_status == "undeliverable"
    entry = test_db.query(SuppressionEntry).filter_by(value="gone@acme.io").first()
    assert entry is not None and entry.source == "bounce"


def test_soft_bounce_marks_email_but_keeps_cadence(test_db):
    lead = _make_lead(test_db, email="full@acme.io")
    sent = OutreachEmail(lead_id=lead.id, step_number=1, subject="s", body="b",
                         status="sent", sent_at=utcnow())
    followup = OutreachEmail(lead_id=lead.id, step_number=2, subject="s2", body="b2",
                             status="scheduled", scheduled_at=utcnow() + timedelta(days=3))
    test_db.add_all([sent, followup])
    test_db.commit()

    result = handle_bounce(test_db, "full@acme.io", hard=False, diagnostic="452 4.2.2 Mailbox full")

    test_db.refresh(sent)
    test_db.refresh(followup)
    assert result["status"] == "soft_bounce"
    assert sent.status == "bounced"
    assert followup.status == "scheduled"
    assert test_db.query(SuppressionEntry).count() == 0


def test_bounce_for_unknown_recipient_is_noop(test_db):
    result = handle_bounce(test_db, "stranger@nowhere.io", hard=True)
    assert result["status"] == "no_lead"


# ---------------------------------------------------------------------------
# IMAP poller routing
# ---------------------------------------------------------------------------

class _FakeImap:
    """Minimal IMAP double yielding one preloaded RFC822 message."""

    def __init__(self, raw_messages):
        self._raw = raw_messages

    def login(self, *a):
        pass

    def select(self, *a):
        pass

    def search(self, *a):
        ids = b" ".join(str(i + 1).encode() for i in range(len(self._raw)))
        return "OK", [ids]

    def fetch(self, num, spec):
        return "OK", [(b"1 (RFC822)", self._raw[int(num) - 1])]

    def logout(self):
        pass


def test_poller_routes_dsn_to_bounce_handler_not_reply(test_db):
    from app.services.mailbox_service import encrypt_secret, poll_mailbox_replies
    from app.database.models import SendingMailbox

    lead = _make_lead(test_db, email="gone@acme.io")
    sent = OutreachEmail(lead_id=lead.id, step_number=1, subject="s", body="b",
                         status="sent", sent_at=utcnow())
    test_db.add(sent)
    test_db.add(SendingMailbox(
        email="sender@ours.io", smtp_host="smtp.ours.io", smtp_username="sender@ours.io",
        smtp_password_encrypted=encrypt_secret("pw"), imap_enabled=True, imap_host="imap.ours.io",
    ))
    test_db.commit()

    raw = _dsn_message(recipient="gone@acme.io").as_bytes()
    with patch("app.services.reply_service.handle_reply") as mock_reply:
        result = poll_mailbox_replies(test_db, imap_factory=lambda h, p: _FakeImap([raw]))

    mock_reply.assert_not_called()
    assert result["bounces"] == 1
    test_db.refresh(sent)
    assert sent.status == "bounced"


# ---------------------------------------------------------------------------
# On-demand endpoint
# ---------------------------------------------------------------------------

def test_verification_endpoint(client, monkeypatch):
    monkeypatch.setattr(ev, "_resolve_mx_cached", lambda d: _mx_ok(d))
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post("/email-verification", json={"email": "jane@acme.io"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "valid"

    r = client.post("/email-verification", json={}, headers=headers)
    assert r.status_code == 422

    assert client.post("/email-verification", json={"email": "x@y.io"}).status_code in (401, 403)


# ---------------------------------------------------------------------------
# Lead detail API exposes the stored verification result
# ---------------------------------------------------------------------------

def test_lead_detail_includes_verification_fields(client, test_db):
    from app.services.tenancy import get_default_org

    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    lead = _make_lead(test_db, org_id=get_default_org(test_db).id)
    lead.email_verification_status = "undeliverable"
    lead.email_verified_at = utcnow()
    lead.email_verification_detail = {"reason": "Domain does not exist (NXDOMAIN)"}
    test_db.commit()

    resp = client.get(f"/leads/{lead.id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email_verification_status"] == "undeliverable"
    assert body["email_verification_reason"] == "Domain does not exist (NXDOMAIN)"
    assert body["email_verified_at"] is not None


def test_lead_detail_verification_fields_null_before_first_check(client, test_db):
    from app.services.tenancy import get_default_org

    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    lead = _make_lead(test_db, org_id=get_default_org(test_db).id)
    resp = client.get(f"/leads/{lead.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email_verification_status"] is None
    assert resp.json()["email_verification_reason"] is None
