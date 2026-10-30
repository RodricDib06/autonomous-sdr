"""
Regression tests for holes that existing tests didn't cover:

  - `filter(..., not Lead.archived)` is Python `not` on a column — it evaluates
    to the constant False, so export and rep assignments silently matched nothing
  - SSE endpoints skipped auth entirely when ?token= was omitted
  - /ingest/email-reply ignored WEBHOOK_SECRET, unlike every other ingest route
  - /track/click redirected anywhere for any id — an open redirect
"""
from unittest.mock import patch

import pytest

from app.database.models import Lead, OutreachEmail, User
from app.services.assignment_service import get_rep_assignments
from app.services.auth_service import hash_password


def _admin_headers(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_lead(db, email="jane@acme.com", **kwargs):
    lead = Lead(name="Jane", email=email, company="Acme", **kwargs)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


# ---------------------------------------------------------------------------
# Archived filter
# ---------------------------------------------------------------------------

def test_export_includes_completed_unarchived_leads(client, test_session_factory):
    headers = _admin_headers(client)
    db = test_session_factory()
    _make_lead(db, email="live@acme.com", status="complete", archived=False)
    _make_lead(db, email="gone@acme.com", status="complete", archived=True)
    db.close()

    r = client.get("/leads/export", headers=headers)
    assert r.status_code == 200
    emails = [row["email"] for row in r.json()["export"]]
    assert emails == ["live@acme.com"]


def test_rep_assignments_exclude_only_archived(test_db):
    rep = User(email="rep@test.com", password_hash=hash_password("x"), role="rep")
    test_db.add(rep)
    test_db.commit()
    _make_lead(test_db, email="a@acme.com", assigned_to_id=rep.id, archived=False)
    _make_lead(test_db, email="b@acme.com", assigned_to_id=rep.id, archived=True)

    assert [lead.email for lead in get_rep_assignments(test_db, rep.id)] == ["a@acme.com"]


# ---------------------------------------------------------------------------
# SSE auth
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/events/stream",
    "/leads/some-lead/pipeline/stream",
    "/leads/some-lead/outreach/generate/stream",
])
@pytest.mark.parametrize("query", ["", "?token=", "?token=not-a-jwt"])
def test_sse_requires_valid_token(client, path, query):
    assert client.get(path + query).status_code == 401


def test_pipeline_stream_hides_other_orgs_leads(client):
    headers = _admin_headers(client)
    token = headers["Authorization"].split()[1]
    assert client.get(f"/leads/missing/pipeline/stream?token={token}").status_code == 404


# ---------------------------------------------------------------------------
# /ingest/email-reply webhook secret
# ---------------------------------------------------------------------------

def test_email_reply_rejects_missing_secret(client, test_session_factory):
    db = test_session_factory()
    lead_id = _make_lead(db).id
    db.close()

    with patch("app.routers.ingest.settings") as mock_settings:
        mock_settings.WEBHOOK_SECRET = "correct-secret"
        r = client.post("/ingest/email-reply", json={
            "lead_id": lead_id, "reply_text": "Please remove me from your list",
        })
    assert r.status_code == 403


def test_email_reply_accepts_correct_secret(client, test_session_factory):
    db = test_session_factory()
    lead_id = _make_lead(db).id
    db.close()

    with patch("app.routers.ingest.settings") as mock_settings:
        mock_settings.WEBHOOK_SECRET = "correct-secret"
        r = client.post(
            "/ingest/email-reply",
            json={"lead_id": lead_id, "reply_text": "Please remove me from your list"},
            headers={"X-Webhook-Secret": "correct-secret"},
        )
    assert r.status_code == 202


# ---------------------------------------------------------------------------
# /track/click open redirect
# ---------------------------------------------------------------------------

def test_click_unknown_email_does_not_redirect(client):
    r = client.get("/track/click/nope?url=https://evil.example", follow_redirects=False)
    assert r.status_code == 404
    assert "location" not in r.headers


def test_click_known_email_redirects(client, test_session_factory):
    db = test_session_factory()
    lead = _make_lead(db)
    email = OutreachEmail(lead_id=lead.id, step_number=1, subject="s", body="b", status="sent")
    db.add(email)
    db.commit()
    email_id = email.id
    db.close()

    r = client.get(f"/track/click/{email_id}?url=https://acme.com/pricing", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://acme.com/pricing"
