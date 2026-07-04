"""
Tests for the human-in-the-loop approval workflow (autonomy dial).

Coverage:
  - autonomy dial: get/set, validation, RBAC
  - OutreachAgent honours the mode (pending_approval vs scheduled, no step-1 send)
  - approve (with inline edits), reject, approve-all
  - draft mode refuses to queue sends
  - scheduled sender ignores pending_approval rows and holds draft orgs
  - org scoping: cannot approve another org's email
"""
from unittest.mock import patch

from app.database.models import Lead, OutreachEmail, User
from app.services.auth_service import hash_password
from app.services.tenancy import create_org, get_default_org, set_org_setting


def _login(client, email, password="password123"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _register_first_admin(client, email="admin@test.com"):
    client.post("/auth/register", json={"email": email, "password": "password123", "role": "rep"})
    return _login(client, email)


def _make_lead(db, org_id, email="lead@corp.com"):
    lead = Lead(name="Jane", email=email, company="Corp", org_id=org_id)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _make_pending_email(db, lead, step=1, subject="s", body="b"):
    e = OutreachEmail(
        lead_id=lead.id, step_number=step, subject=subject, body=body,
        status="pending_approval",
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


# ---------------------------------------------------------------------------
# Autonomy dial
# ---------------------------------------------------------------------------

def test_autonomy_defaults_to_auto(client):
    headers = _register_first_admin(client)
    r = client.get("/outreach/autonomy", headers=headers)
    assert r.status_code == 200
    assert r.json()["mode"] == "auto"
    assert r.json()["pending_count"] == 0


def test_set_autonomy_mode(client):
    headers = _register_first_admin(client)
    r = client.put("/outreach/autonomy", json={"mode": "approve"}, headers=headers)
    assert r.status_code == 200
    assert client.get("/outreach/autonomy", headers=headers).json()["mode"] == "approve"


def test_set_autonomy_rejects_invalid_mode(client):
    headers = _register_first_admin(client)
    r = client.put("/outreach/autonomy", json={"mode": "yolo"}, headers=headers)
    assert r.status_code == 422


def test_set_autonomy_requires_auth(client):
    assert client.put("/outreach/autonomy", json={"mode": "auto"}).status_code in (401, 403)


# ---------------------------------------------------------------------------
# Agent honours the dial
# ---------------------------------------------------------------------------

def _run_agent(db, lead):
    from app.agents.outreach_agent import OutreachAgent
    agent = OutreachAgent.__new__(OutreachAgent)  # skip LLM client init
    agent._ai = None
    agent._judge = None

    fake_quality = {"overall_score": 0.9, "issues": [], "improvement_hint": ""}
    with patch.object(OutreachAgent, "_personalise_with_judge",
                      return_value=("Subj", "Body", fake_quality)), \
         patch("app.config.settings.SMTP_HOST", ""):
        return agent.run(db, lead.id, {})


def test_agent_approve_mode_creates_pending_emails(test_db):
    org = get_default_org(test_db)
    set_org_setting(test_db, org.id, "autonomy_mode", "approve")
    lead = _make_lead(test_db, org.id)

    result = _run_agent(test_db, lead)

    assert result["status"] == "pending_approval"
    assert "held_for_approval" in result["step1_send"]
    statuses = {e.status for e in test_db.query(OutreachEmail).filter_by(lead_id=lead.id)}
    assert statuses == {"pending_approval"}


def test_agent_auto_mode_schedules(test_db):
    org = get_default_org(test_db)
    set_org_setting(test_db, org.id, "autonomy_mode", "auto")
    lead = _make_lead(test_db, org.id)

    result = _run_agent(test_db, lead)

    assert result["status"] == "scheduled"
    statuses = {e.status for e in test_db.query(OutreachEmail).filter_by(lead_id=lead.id)}
    assert statuses == {"scheduled"}


# ---------------------------------------------------------------------------
# Approve / reject / bulk
# ---------------------------------------------------------------------------

def test_approve_email_flow(client, test_session_factory):
    headers = _register_first_admin(client)
    client.put("/outreach/autonomy", json={"mode": "approve"}, headers=headers)

    db = test_session_factory()
    lead = _make_lead(db, get_default_org(db).id)
    email = _make_pending_email(db, lead)
    email_id = email.id
    db.close()

    r = client.get("/outreach/approvals", headers=headers)
    assert r.json()["total"] == 1
    assert r.json()["emails"][0]["lead_name"] == "Jane"

    r = client.post(f"/outreach/approvals/{email_id}/approve", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "scheduled"

    db = test_session_factory()
    row = db.query(OutreachEmail).filter_by(id=email_id).first()
    assert row.status == "scheduled"
    assert row.approved_by_id is not None
    db.close()


def test_approve_with_inline_edits(client, test_session_factory):
    headers = _register_first_admin(client)
    client.put("/outreach/autonomy", json={"mode": "approve"}, headers=headers)

    db = test_session_factory()
    lead = _make_lead(db, get_default_org(db).id)
    email = _make_pending_email(db, lead, subject="old", body="old body")
    email_id = email.id
    db.close()

    r = client.post(
        f"/outreach/approvals/{email_id}/approve",
        json={"subject": "Better subject", "body": "Better body"},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["edited"] is True

    db = test_session_factory()
    row = db.query(OutreachEmail).filter_by(id=email_id).first()
    assert row.subject == "Better subject"
    assert row.body == "Better body"
    db.close()


def test_reject_email(client, test_session_factory):
    headers = _register_first_admin(client)

    db = test_session_factory()
    lead = _make_lead(db, get_default_org(db).id)
    email = _make_pending_email(db, lead)
    email_id = email.id
    db.close()

    r = client.post(
        f"/outreach/approvals/{email_id}/reject",
        json={"reason": "too pushy"},
        headers=headers,
    )
    assert r.status_code == 200

    db = test_session_factory()
    row = db.query(OutreachEmail).filter_by(id=email_id).first()
    assert row.status == "rejected"
    assert row.rejection_reason == "too pushy"
    db.close()


def test_approve_all(client, test_session_factory):
    headers = _register_first_admin(client)
    client.put("/outreach/autonomy", json={"mode": "approve"}, headers=headers)

    db = test_session_factory()
    lead = _make_lead(db, get_default_org(db).id)
    for step in (1, 2, 3):
        _make_pending_email(db, lead, step=step)
    db.close()

    r = client.post("/outreach/approvals/approve-all", headers=headers)
    assert r.json()["approved"] == 3

    db = test_session_factory()
    assert db.query(OutreachEmail).filter_by(status="scheduled").count() == 3
    db.close()


def test_draft_mode_blocks_approval(client, test_session_factory):
    headers = _register_first_admin(client)
    client.put("/outreach/autonomy", json={"mode": "draft"}, headers=headers)

    db = test_session_factory()
    lead = _make_lead(db, get_default_org(db).id)
    email = _make_pending_email(db, lead)
    email_id = email.id
    db.close()

    r = client.post(f"/outreach/approvals/{email_id}/approve", json={}, headers=headers)
    assert r.status_code == 409
    assert client.post("/outreach/approvals/approve-all", headers=headers).status_code == 409


def test_cannot_approve_other_orgs_email(client, test_session_factory):
    headers = _register_first_admin(client)

    db = test_session_factory()
    org_b = create_org(db, "Rival")
    db.add(User(email="boss@rival.com", password_hash=hash_password("password123"),
                role="admin", org_id=org_b.id))
    db.commit()
    lead_b = _make_lead(db, org_b.id, email="lead@rival.com")
    email_b = _make_pending_email(db, lead_b)
    email_id = email_b.id
    db.close()

    r = client.post(f"/outreach/approvals/{email_id}/approve", json={}, headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Scheduled sender interaction
# ---------------------------------------------------------------------------

def test_sender_ignores_pending_approval_rows(test_db):
    from app.agents.outreach_agent import send_pending_scheduled_emails
    from datetime import datetime, timedelta

    org = get_default_org(test_db)
    lead = _make_lead(test_db, org.id)
    e = _make_pending_email(test_db, lead)
    e.scheduled_at = datetime.utcnow() - timedelta(minutes=10)
    test_db.commit()

    with patch.multiple(
        "app.config.settings",
        OUTREACH_WEEKDAYS_ONLY=False, OUTREACH_SEND_WINDOW_START=0,
        OUTREACH_SEND_WINDOW_END=24, OUTREACH_DAILY_SEND_LIMIT=200, SMTP_HOST="",
    ):
        summary = send_pending_scheduled_emails(test_db)

    assert summary["sent"] == 0
    test_db.refresh(e)
    assert e.status == "pending_approval"


def test_sender_holds_draft_org_scheduled_rows(test_db):
    from app.agents.outreach_agent import send_pending_scheduled_emails
    from datetime import datetime, timedelta

    org = get_default_org(test_db)
    set_org_setting(test_db, org.id, "autonomy_mode", "draft")
    lead = _make_lead(test_db, org.id)
    e = OutreachEmail(
        lead_id=lead.id, step_number=2, subject="s", body="b",
        status="scheduled", scheduled_at=datetime.utcnow() - timedelta(minutes=10),
    )
    test_db.add(e)
    test_db.commit()

    with patch.multiple(
        "app.config.settings",
        OUTREACH_WEEKDAYS_ONLY=False, OUTREACH_SEND_WINDOW_START=0,
        OUTREACH_SEND_WINDOW_END=24, OUTREACH_DAILY_SEND_LIMIT=200, SMTP_HOST="",
    ):
        summary = send_pending_scheduled_emails(test_db)

    assert summary["sent"] == 0
    assert summary["skipped"] == 1
    test_db.refresh(e)
    assert e.status == "scheduled"
