"""
Tests for sending mailboxes: credential encryption, warm-up ramp, rotation,
IMAP reply polling (mocked), API CRUD + password non-disclosure, and the
shared reply pipeline.
"""
from datetime import timedelta
from email.message import EmailMessage
from unittest.mock import MagicMock

from app.database.models import Lead, OutreachEmail, SendingMailbox
from app.services.mailbox_service import (
    decrypt_secret,
    effective_daily_limit,
    encrypt_secret,
    pick_mailbox,
    poll_mailbox_replies,
)
from app.services.tenancy import get_default_org
from app.utils.time import utcnow


def _make_mailbox(db, org_id, email="rep@corp.com", warmup=None, limit=50, imap=False, active=True):
    m = SendingMailbox(
        org_id=org_id,
        email=email,
        smtp_host="smtp.corp.com",
        smtp_username=email,
        smtp_password_encrypted=encrypt_secret("hunter2"),
        daily_limit=limit,
        warmup_started_at=warmup,
        imap_enabled=imap,
        imap_host="imap.corp.com" if imap else None,
        is_active=active,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _make_lead(db, org_id, email="lead@corp.com"):
    lead = Lead(name="Jane", email=email, company="Corp", org_id=org_id)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


# ---------------------------------------------------------------------------
# Encryption & warm-up
# ---------------------------------------------------------------------------

def test_secret_roundtrip():
    token = encrypt_secret("s3cret!")
    assert token != "s3cret!"
    assert decrypt_secret(token) == "s3cret!"


def test_warmup_ramp(test_db):
    org = get_default_org(test_db)
    fresh = _make_mailbox(test_db, org.id, warmup=utcnow())
    assert effective_daily_limit(fresh) == 10

    week_old = _make_mailbox(test_db, org.id, email="old@corp.com", warmup=utcnow() - timedelta(days=7))
    assert effective_daily_limit(week_old) == 45  # 10 + 5*7

    warm = _make_mailbox(test_db, org.id, email="warm@corp.com", warmup=utcnow() - timedelta(days=60))
    assert effective_daily_limit(warm) == 50  # capped at daily_limit

    no_warmup = _make_mailbox(test_db, org.id, email="nw@corp.com", warmup=None)
    assert effective_daily_limit(no_warmup) == 50


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------

def test_pick_mailbox_skips_exhausted(test_db):
    org = get_default_org(test_db)
    lead = _make_lead(test_db, org.id)
    box_a = _make_mailbox(test_db, org.id, email="a@corp.com", warmup=utcnow())  # limit 10
    box_b = _make_mailbox(test_db, org.id, email="b@corp.com", warmup=None)

    # Exhaust box A's warm-up allowance
    for _ in range(10):
        test_db.add(OutreachEmail(
            lead_id=lead.id, step_number=1, subject="s", body="b",
            status="sent", sent_at=utcnow(), mailbox_id=box_a.id,
        ))
    test_db.commit()

    picked = pick_mailbox(test_db, org.id)
    assert picked.id == box_b.id


def test_pick_mailbox_none_when_all_exhausted(test_db):
    org = get_default_org(test_db)
    lead = _make_lead(test_db, org.id)
    box = _make_mailbox(test_db, org.id, warmup=utcnow())
    for _ in range(10):
        test_db.add(OutreachEmail(
            lead_id=lead.id, step_number=1, subject="s", body="b",
            status="sent", sent_at=utcnow(), mailbox_id=box.id,
        ))
    test_db.commit()
    assert pick_mailbox(test_db, org.id) is None


def test_pick_mailbox_ignores_inactive_and_other_orgs(test_db):
    from app.services.tenancy import create_org
    org = get_default_org(test_db)
    other = create_org(test_db, "Other")
    _make_mailbox(test_db, org.id, email="off@corp.com", active=False)
    _make_mailbox(test_db, other.id, email="theirs@corp.com")
    assert pick_mailbox(test_db, org.id) is None


# ---------------------------------------------------------------------------
# IMAP polling (mocked connection)
# ---------------------------------------------------------------------------

def _fake_imap_with_message(from_addr: str, body: str):
    msg = EmailMessage()
    msg["From"] = f"Jane Doe <{from_addr}>"
    msg["Subject"] = "Re: Quick question"
    msg.set_content(body)

    conn = MagicMock()
    conn.search.return_value = ("OK", [b"1"])
    conn.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])
    return conn


def test_poll_replies_matches_lead_and_stops_cadence(test_db):
    org = get_default_org(test_db)
    lead = _make_lead(test_db, org.id, email="jane@lead.com")
    test_db.add(OutreachEmail(
        lead_id=lead.id, step_number=1, subject="s", body="b",
        status="sent", sent_at=utcnow(),
    ))
    test_db.add(OutreachEmail(
        lead_id=lead.id, step_number=2, subject="s2", body="b2",
        status="scheduled", scheduled_at=utcnow() + timedelta(days=3),
    ))
    test_db.commit()
    _make_mailbox(test_db, org.id, imap=True)

    conn = _fake_imap_with_message("jane@lead.com", "Sounds interesting, tell me more!")
    summary = poll_mailbox_replies(test_db, imap_factory=lambda h, p: conn)

    assert summary["matched"] == 1
    statuses = {e.step_number: e.status for e in test_db.query(OutreachEmail).all()}
    assert statuses[1] == "replied"
    assert statuses[2] == "cancelled"


def test_poll_replies_unsubscribe_keyword_suppresses(test_db):
    from app.services.compliance import is_suppressed

    org = get_default_org(test_db)
    _make_lead(test_db, org.id, email="done@lead.com")
    _make_mailbox(test_db, org.id, imap=True)

    conn = _fake_imap_with_message("done@lead.com", "Please remove me from your list")
    summary = poll_mailbox_replies(test_db, imap_factory=lambda h, p: conn)

    assert summary["matched"] == 1
    assert is_suppressed(test_db, "done@lead.com", org_id=org.id) is not None


def test_poll_replies_ignores_unknown_sender(test_db):
    org = get_default_org(test_db)
    _make_mailbox(test_db, org.id, imap=True)

    conn = _fake_imap_with_message("stranger@nowhere.com", "Who is this?")
    summary = poll_mailbox_replies(test_db, imap_factory=lambda h, p: conn)

    assert summary["processed"] == 1
    assert summary["matched"] == 0


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _admin_headers(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


MAILBOX_PAYLOAD = {
    "email": "rep@corp.com",
    "display_name": "Rep Person",
    "smtp_host": "smtp.corp.com",
    "smtp_username": "rep@corp.com",
    "smtp_password": "hunter2",
    "daily_limit": 40,
}


def test_mailbox_crud_and_no_password_leak(client, test_session_factory):
    headers = _admin_headers(client)

    r = client.post("/mailboxes", json=MAILBOX_PAYLOAD, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["warming_up"] is True
    assert body["effective_daily_limit"] == 10
    assert "hunter2" not in r.text
    assert "password" not in body

    r = client.get("/mailboxes", headers=headers)
    assert r.json()["total"] == 1
    assert "hunter2" not in r.text

    mailbox_id = body["id"]
    r = client.delete(f"/mailboxes/{mailbox_id}", headers=headers)
    assert r.status_code == 200

    db = test_session_factory()
    assert db.query(SendingMailbox).filter_by(id=mailbox_id).first().is_active is False
    db.close()


def test_mailbox_create_requires_manager(client):
    headers = _admin_headers(client)
    client.post("/auth/register", json={"email": "rep@test.com", "password": "password123", "role": "rep"}, headers=headers)
    r = client.post("/auth/login", json={"email": "rep@test.com", "password": "password123"})
    rep_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    assert client.get("/mailboxes", headers=rep_headers).status_code == 200
    assert client.post("/mailboxes", json=MAILBOX_PAYLOAD, headers=rep_headers).status_code == 403
