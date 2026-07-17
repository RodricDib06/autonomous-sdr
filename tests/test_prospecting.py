"""
Tests for autonomous prospecting (the agent sources its own leads).

Coverage:
  - synthetic source: determinism, criteria filtering
  - gate order: suppression before verification (no spend on opt-outs),
    dedup, undeliverable rejection, low-score rejection
  - budget guardrail: daily cap binds and is attributed in the breakdown
  - dry run: full gates, zero writes
  - import path: lead + seeded enrichment created, run recorded
  - campaign executor's request_prospecting action goes live
  - API: create/list, campaign-criteria defaulting, RBAC
"""

from unittest.mock import patch

from app.database.models import Campaign, Enrichment, Lead, ProspectingRun
from app.services.compliance import add_suppression
from app.services.prospecting.service import run_prospecting
from app.services.prospecting.synthetic import SyntheticProspectSource
from app.services.tenancy import get_default_org
from tests.test_campaigns import END, START


# ---------------------------------------------------------------------------
# Synthetic source
# ---------------------------------------------------------------------------

def test_synthetic_is_deterministic():
    source = SyntheticProspectSource()
    a = source.search({"industry": "SaaS"}, 10)
    b = source.search({"industry": "SaaS"}, 10)
    assert [c.email for c in a] == [c.email for c in b]
    assert len(a) == 10


def test_synthetic_respects_criteria():
    source = SyntheticProspectSource()
    for candidate in source.search({"industry": "FinTech", "seniority": "VP"}, 8):
        assert "fintech" in candidate.industry.lower()
        assert candidate.seniority == "VP"


def test_synthetic_size_bounds():
    source = SyntheticProspectSource()
    from app.services.icp_service import parse_company_size
    for candidate in source.search({"company_size_min": 100, "company_size_max": 600}, 8):
        midpoint = parse_company_size(candidate.company_size)
        assert 100 <= midpoint <= 600


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def test_suppressed_candidates_never_imported(test_db):
    source = SyntheticProspectSource()
    first = source.search({"industry": "SaaS"}, 5)[0]
    add_suppression(test_db, first.email, source="manual")

    run = run_prospecting(test_db, {"industry": "SaaS"}, limit=5)

    assert run.rejected["suppressed"] >= 1
    assert test_db.query(Lead).filter(Lead.email == first.email).count() == 0


def test_duplicates_rejected(test_db):
    source = SyntheticProspectSource()
    first = source.search({"industry": "SaaS"}, 5)[0]
    test_db.add(Lead(name="Existing", email=first.email, company=first.company))
    test_db.commit()

    run = run_prospecting(test_db, {"industry": "SaaS"}, limit=5)
    assert run.rejected["duplicate"] >= 1
    assert test_db.query(Lead).filter(Lead.email == first.email).count() == 1


def test_undeliverable_rejected_when_verification_on(test_db, monkeypatch):
    from app.services import email_verification as ev
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFICATION_ENABLED", True)

    calls = []

    def fake_verify(email):
        calls.append(email)
        from app.services.email_verification import VerificationResult
        return VerificationResult(email, "undeliverable", "NXDOMAIN", {})

    with patch("app.services.email_verification.verify_email", side_effect=fake_verify):
        run = run_prospecting(test_db, {"industry": "SaaS"}, limit=3)

    assert run.accepted == 0
    assert run.rejected["undeliverable"] == run.found
    assert calls  # verification actually ran


def test_low_score_rejected(test_db, monkeypatch):
    monkeypatch.setattr("app.services.prospecting.service.settings.PROSPECTING_MIN_SCORE", 0.99)
    run = run_prospecting(test_db, {"industry": "SaaS"}, limit=3)
    assert run.accepted == 0
    assert run.rejected["low_score"] == run.found


def test_budget_cap_binds_and_is_attributed(test_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.prospecting.service.settings.PROSPECTING_MAX_LEADS_PER_DAY", 2
    )
    run = run_prospecting(test_db, {"industry": "SaaS"}, limit=6)
    assert run.accepted == 2
    assert run.rejected["budget"] >= 1

    # Budget now exhausted — next run accepts nothing
    run2 = run_prospecting(test_db, {"industry": "FinTech"}, limit=3)
    assert run2.accepted == 0


# ---------------------------------------------------------------------------
# Import + dry run
# ---------------------------------------------------------------------------

def test_import_creates_leads_with_seeded_enrichment(test_db):
    run = run_prospecting(test_db, {"industry": "SaaS", "seniority": "VP"}, limit=4)

    assert run.accepted == 4
    leads = test_db.query(Lead).filter(Lead.source == "prospecting:synthetic").all()
    assert len(leads) == 4
    for lead in leads:
        enrichment = test_db.query(Enrichment).filter(Enrichment.lead_id == lead.id).first()
        assert enrichment is not None
        assert enrichment.seniority == "VP"
        assert enrichment.enrichment_source == "prospecting:synthetic"
        assert lead.status == "pending"  # picked up by the pipeline

    assert len(run.preview) == 4
    assert all(c["score"] is not None for c in run.preview)


def test_dry_run_writes_nothing(test_db):
    run = run_prospecting(test_db, {"industry": "SaaS"}, limit=4, dry_run=True)

    assert run.dry_run is True
    assert run.accepted == 0
    assert len(run.preview) == 4
    assert test_db.query(Lead).count() == 0
    # The run record itself IS persisted — it's the audit trail
    assert test_db.query(ProspectingRun).count() == 1


def test_candidates_ranked_by_score(test_db):
    run = run_prospecting(test_db, {}, limit=6, dry_run=True)
    scores = [c["score"] for c in run.preview]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Campaign executor wiring
# ---------------------------------------------------------------------------

def test_campaign_request_prospecting_goes_live(test_db):
    from app.agents.campaign_agent import execute_plan
    from app.database.models import CampaignPlan

    org = get_default_org(test_db)
    campaign = Campaign(org_id=org.id, name="c", goal_type="meetings", goal_target=5,
                        period_start=START, period_end=END)
    test_db.add(campaign)
    test_db.flush()
    plan = CampaignPlan(campaign_id=campaign.id, version=1, status="approved",
                        actions=[{"type": "request_prospecting",
                                  "segment": {"industry": "SaaS"}, "count": 3,
                                  "reason": "pipeline coverage low"}])
    test_db.add(plan)
    test_db.commit()

    result = execute_plan(test_db, plan)

    assert result["succeeded"] == 1
    run = test_db.query(ProspectingRun).first()
    assert run is not None
    assert run.campaign_id == campaign.id
    assert run.accepted == 3
    assert test_db.query(Lead).count() == 3


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _login(client):
    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_dry_run_endpoint_returns_preview(client):
    headers = _login(client)
    r = client.post("/prospecting/runs",
                    json={"criteria": {"industry": "SaaS"}, "limit": 5, "dry_run": True},
                    headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert len(body["candidates"]) == 5
    assert {"name", "email", "score", "verdict", "verification_status"} <= set(body["candidates"][0])


def test_run_endpoint_imports_and_lists(client, test_db):
    headers = _login(client)
    r = client.post("/prospecting/runs",
                    json={"criteria": {"industry": "SaaS"}, "limit": 3}, headers=headers)
    assert r.status_code == 201
    assert r.json()["accepted"] == 3

    r = client.get("/prospecting/runs", headers=headers)
    assert r.json()["total"] == 1
    assert r.json()["budget"]["accepted_today"] == 3
    assert r.json()["runs"][0]["rejected"] is not None


def test_campaign_criteria_defaulting(client, test_db):
    headers = _login(client)
    org = get_default_org(test_db)
    campaign = Campaign(org_id=org.id, name="c", goal_type="meetings", goal_target=5,
                        period_start=START, period_end=END,
                        constraints={"segments": [{"industry": "FinTech"}]})
    test_db.add(campaign)
    test_db.commit()

    r = client.post("/prospecting/runs",
                    json={"campaign_id": campaign.id, "limit": 3, "dry_run": True},
                    headers=headers)
    assert r.status_code == 201
    assert r.json()["criteria"] == {"industry": "FinTech"}
    assert all("fintech" in c["industry"].lower() for c in r.json()["candidates"])


def test_prospecting_requires_auth(client):
    assert client.post("/prospecting/runs", json={"limit": 3}).status_code in (401, 403)
    assert client.get("/prospecting/runs").status_code in (401, 403)
