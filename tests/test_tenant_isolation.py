"""
Cross-tenant isolation: an admin of org B must not read or change anything
that belongs to org A.

The route sweep enumerates the live route table instead of a hand-kept list,
so a new /leads/{lead_id}/... endpoint is covered the moment it exists.
"""
import re

import pytest
from fastapi.routing import APIRoute

from app.database.models import (
    BookingRequest, Conversation, Lead, OutreachEmail, OutreachSequence, User, Verdict,
)
from app.services.auth_service import hash_password
from app.services.tenancy import create_org, get_default_org
from app.utils.time import utcnow


def _login(client, email, password="password123"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db, org, email, role="admin"):
    user = User(email=email, password_hash=hash_password("password123"), role=role, org_id=org.id)
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def two_orgs(test_session_factory):
    """Org A (the default org) owns a fully populated lead; org B owns its own."""
    db = test_session_factory()
    org_a = get_default_org(db)
    org_b = create_org(db, "Rival Inc")
    _make_user(db, org_a, "admin-a@a.com")
    rep_b = _make_user(db, org_b, "rep-b@b.com", role="rep")
    _make_user(db, org_b, "admin-b@b.com")

    lead_a = Lead(name="Ann", email="ann@a-corp.com", company="ACorp", org_id=org_a.id,
                  status="complete", conversion_status="qualified", archived=False,
                  updated_at=utcnow())
    lead_b = Lead(name="Bob", email="bob@b-corp.com", company="BCorp", org_id=org_b.id,
                  status="complete", conversion_status="qualified", archived=False,
                  assigned_to_id=rep_b.id, updated_at=utcnow())
    db.add_all([lead_a, lead_b])
    db.commit()
    for lead, verdict in ((lead_a, "Hot"), (lead_b, "Warm")):
        db.add(Verdict(lead_id=lead.id, final_verdict=verdict, confidence_score=0.9))
    email_a = OutreachEmail(lead_id=lead_a.id, step_number=1, subject="s", body="b", status="sent")
    conv_a = Conversation(lead_id=lead_a.id, channel="email", messages=[], needs_human=True)
    booking_a = BookingRequest(lead_id=lead_a.id, status="link_sent")
    db.add_all([email_a, conv_a, booking_a])
    db.commit()
    ids = {
        "lead_a": lead_a.id, "lead_b": lead_b.id, "email_a": email_a.id,
        "conv_a": conv_a.id, "booking_a": booking_a.id,
        "org_a": org_a.id, "org_b": org_b.id,
    }
    db.close()
    return ids


# ---------------------------------------------------------------------------
# Route sweep
# ---------------------------------------------------------------------------

_PARAM_TO_FIXTURE = {
    "lead_id": "lead_a", "primary_id": "lead_a", "duplicate_id": "lead_a",
    "email_id": "email_a", "conv_id": "conv_a", "booking_id": "booking_a",
}

# Routes that take a lead-owned id but are deliberately public: recipients hit
# them from an email client, where there is no session to scope by.
_PUBLIC = {"/track/open/{email_id}", "/track/click/{email_id}", "/unsubscribe/{email_id}"}


def _guarded_routes():
    from app.main import app
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in _PUBLIC:
            continue
        params = set(re.findall(r"{(\w+)}", route.path))
        if params & set(_PARAM_TO_FIXTURE):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, route.path


@pytest.mark.parametrize("method,path", list(_guarded_routes()))
def test_other_orgs_records_are_invisible(client, two_orgs, method, path):
    headers = _login(client, "admin-b@b.com")

    def fill(m):
        name = m.group(1)
        return two_orgs[_PARAM_TO_FIXTURE[name]] if name in _PARAM_TO_FIXTURE else "x"

    url = re.sub(r"{(\w+)}", fill, path)
    sep = "&" if "?" in url else "?"
    token = headers["Authorization"].split()[1]
    r = client.request(method, f"{url}{sep}token={token}", headers=headers, json={})
    assert r.status_code == 404, f"{method} {path} → {r.status_code}: {r.text[:200]}"


def test_sweep_is_not_vacuous():
    assert len(list(_guarded_routes())) >= 35


def test_own_lead_still_visible(client, two_orgs):
    headers = _login(client, "admin-a@a.com")
    assert client.get(f"/leads/{two_orgs['lead_a']}", headers=headers).status_code == 200


# ---------------------------------------------------------------------------
# Collection endpoints — org B must see only org B's numbers
# ---------------------------------------------------------------------------

def _b(client):
    return _login(client, "admin-b@b.com")


def test_lead_stats_scoped(client, two_orgs):
    body = client.get("/leads/stats", headers=_b(client)).json()
    assert body["total_leads"] == 1
    assert body["verdict_breakdown"] == {"hot": 0, "warm": 1, "cold": 0}


def test_trend_scoped(client, two_orgs):
    body = client.get("/leads/trend", headers=_b(client)).json()
    assert sum(d["total"] for d in body["data"]) == 1


def test_hot_leads_scoped(client, two_orgs):
    assert client.get("/leads/hot", headers=_b(client)).json()["count"] == 0


def test_export_scoped(client, two_orgs):
    rows = client.get("/leads/export", headers=_b(client)).json()["export"]
    assert [r["email"] for r in rows] == ["bob@b-corp.com"]


def test_quality_report_scoped(client, two_orgs):
    assert client.get("/leads/quality-report", headers=_b(client)).json()["total_leads"] == 1


def test_duplicate_report_scoped(client, two_orgs):
    assert client.get("/leads/duplicates/report", headers=_b(client)).json()["report"]["total_leads"] == 1


def test_batch_cannot_touch_other_org(client, two_orgs, test_session_factory):
    r = client.post("/leads/batch", headers=_b(client), json={
        "action": "archive", "lead_ids": [two_orgs["lead_a"]], "payload": {},
    })
    assert r.status_code == 200
    assert r.json()["succeeded"] == 0 and r.json()["not_found"] == 1
    db = test_session_factory()
    assert db.get(Lead, two_orgs["lead_a"]).archived is False
    db.close()


def test_reprocess_failed_scoped(client, two_orgs, test_session_factory):
    db = test_session_factory()
    db.get(Lead, two_orgs["lead_a"]).status = "failed"
    db.commit()
    db.close()
    from unittest.mock import patch
    with patch("app.services.queue_service.push_lead_job"):
        assert client.post("/leads/reprocess-failed", headers=_b(client)).json()["requeued"] == 0


@pytest.mark.parametrize("path,check", [
    ("/analytics/funnel", lambda b: sum(s["count"] for s in b["stages"]) == 1),
    ("/analytics/powerbi-export", lambda b: [r["email"] for r in b] == ["bob@b-corp.com"]),
    ("/analytics/pipeline-velocity", lambda b: b["total_complete"] == 1),
    ("/analytics/market-intelligence", lambda b: b["global_stats"]["total"] == 1),
    ("/analytics/signal-feed", lambda b: b["count"] == 0),
    ("/outreach/stats", lambda b: b["total_sent"] == 0),
    ("/inbox", lambda b: b["count"] == 0),
    ("/autonomy-feed", lambda b: b["summary"]["total_events"] == 0),
    ("/ab-tests/multi-axis", lambda b: True),
    ("/analytics/llm-costs", lambda b: b["total_calls"] == 0),
])
def test_analytics_scoped(client, two_orgs, path, check):
    r = client.get(path, headers=_b(client))
    assert r.status_code == 200, r.text
    assert check(r.json()), r.json()


def test_rep_performance_lists_only_own_org(client, two_orgs):
    reps = client.get("/analytics/rep-performance", headers=_b(client)).json()["reps"]
    assert {r["rep_email"] for r in reps} <= {"rep-b@b.com", "admin-b@b.com"}


def test_assignment_stats_lists_only_own_org(client, two_orgs):
    stats = client.get("/dashboard/assignment-stats", headers=_b(client)).json()
    assert [s["rep_email"] for s in stats] == ["rep-b@b.com"]


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

def test_users_list_scoped(client, two_orgs):
    emails = {u["email"] for u in client.get("/auth/users", headers=_b(client)).json()}
    assert emails == {"rep-b@b.com", "admin-b@b.com"}


def test_cannot_change_other_orgs_user(client, two_orgs, test_session_factory):
    db = test_session_factory()
    victim = db.query(User).filter_by(email="admin-a@a.com").one().id
    db.close()
    headers = _b(client)
    assert client.put(f"/auth/users/{victim}/role?role=rep", headers=headers).status_code == 404
    assert client.delete(f"/auth/users/{victim}", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# Instance-wide settings
# ---------------------------------------------------------------------------

def test_tenant_admin_cannot_change_instance_settings(client, two_orgs):
    headers = _b(client)
    assert client.post("/config/enrichment-provider?provider=synthetic", headers=headers).status_code == 403
    assert client.post("/config/slack", headers=headers, json={"webhook_url": "https://hooks.slack.com/x"}).status_code == 403
    assert client.post("/optimization/run", headers=headers).status_code == 403


def test_operator_admin_can_change_instance_settings(client, two_orgs):
    r = client.post("/config/enrichment-provider?provider=synthetic", headers=_login(client, "admin-a@a.com"))
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# A/B promotion
# ---------------------------------------------------------------------------

def test_promote_only_touches_own_org(client, two_orgs, test_session_factory):
    db = test_session_factory()
    seq_a = OutreachSequence(name="A", steps=[], is_active=True, org_id=two_orgs["org_a"])
    seq_b1 = OutreachSequence(name="B1", steps=[], is_active=True, org_id=two_orgs["org_b"])
    seq_b2 = OutreachSequence(name="B2", steps=[], is_active=True, org_id=two_orgs["org_b"])
    db.add_all([seq_a, seq_b1, seq_b2])
    db.commit()
    ids = (seq_a.id, seq_b1.id, seq_b2.id)
    db.close()

    headers = _b(client)
    assert client.post(f"/ab-tests/{ids[0]}/promote", headers=headers).status_code == 404
    assert client.post("/ab-tests/does-not-exist/promote", headers=headers).status_code == 404
    assert client.post(f"/ab-tests/{ids[1]}/promote", headers=headers).status_code == 200

    db = test_session_factory()
    active = {s.name: s.is_active for s in db.query(OutreachSequence).all()}
    db.close()
    assert active == {"A": True, "B1": True, "B2": False}
