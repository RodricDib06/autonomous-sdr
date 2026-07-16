"""
Tests for provenance grounding of generated outreach emails.

Coverage:
  - source registry: lead record, enrichment, research notes, template
  - claim extraction: factual anchors in, greetings/CTAs out, cap respected
  - matching: enrichment-backed claims verify, invented metrics don't,
    numeric hard gate, template-sourced sentences verify as "template"
  - ground_email end-to-end report shape + never-raises contract
  - OutreachAgent stores the grounding on each OutreachEmail
  - approval queue API returns the claims payload
"""

from unittest.mock import patch

from app.database.models import Enrichment, Lead, OutreachEmail
from app.services.provenance import (
    build_source_registry,
    extract_claims,
    ground_email,
    match_claim,
)


def _lead(**kwargs):
    defaults = dict(name="Jane Doe", email="jane@acme.io", company="Acme", source="webhook")
    defaults.update(kwargs)
    return Lead(**defaults)


def _enrichment(**kwargs):
    defaults = dict(
        industry="SaaS", job_title="VP of Engineering", seniority="VP",
        company_size="50-200", revenue_estimate="$5M-$20M",
        tech_stack=["AWS", "React"], enrichment_source="domain_heuristics_v1",
    )
    defaults.update(kwargs)
    return Enrichment(**defaults)


_RESEARCH = {
    "research_notes": [
        {
            "tool": "search_web",
            "args": {"query": "Acme funding"},
            "result": {
                "source": "tavily",
                "results": [
                    {"title": "Acme raises $12M Series A", "snippet": "Acme announced a $12M Series A round led by Example Ventures to expand its SaaS platform."},
                ],
            },
        },
        {
            "tool": "check_funding",
            "args": {"company": "Acme"},
            "result": {"recent_funding": True, "headcount_growth": 40, "source": "mock"},
        },
    ],
    "research_summary": "Acme recently raised and is growing fast.",
}


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

def test_registry_includes_all_source_kinds():
    sources = build_source_registry(_lead(), _enrichment(), _RESEARCH, template_text="Hi {first_name}")
    kinds = {s["kind"] for s in sources}
    assert kinds == {"lead_record", "enrichment", "web_search", "funding_signal", "template"}
    assert all(s["id"] and s["title"] is not None and s["text"] for s in sources)


def test_registry_excludes_llm_summary():
    sources = build_source_registry(None, None, _RESEARCH)
    assert not any("growing fast" in s["text"] for s in sources)


def test_registry_handles_missing_everything():
    assert build_source_registry(None, None, None) == []


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

def test_extracts_factual_sentences_only():
    body = (
        "Hi Jane,\n\n"
        "I noticed Acme recently raised a $12M Series A. "
        "We help SaaS teams streamline onboarding. "
        "Would it make sense to connect?\n\nBest,\nSam"
    )
    claims = extract_claims("Quick question", body)
    assert any("$12M" in c for c in claims)
    assert not any(c.startswith("Would it make sense") for c in claims)
    assert not any("Best" in c for c in claims)


def test_greetings_and_short_fragments_are_skipped():
    assert extract_claims("Hello", "Hi Jane,\n\nBest,\nSam") == []


def test_claim_cap():
    body = " ".join(f"Your company raised {i} million dollars in funding round number {i}." for i in range(20))
    assert len(extract_claims("", body)) <= 8


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_research_backed_claim_verifies():
    sources = build_source_registry(_lead(), _enrichment(), _RESEARCH)
    match = match_claim("I saw that Acme announced a $12M Series A round.", sources)
    assert match["status"] == "verified"
    assert match["source_kind"] == "web_search"
    assert match["source_excerpt"]


def test_invented_metric_is_unverified():
    sources = build_source_registry(_lead(), _enrichment(), _RESEARCH)
    match = match_claim("We helped a similar company grow revenue by 300% in 6 weeks.", sources)
    assert match["status"] == "unverified"


def test_numeric_hard_gate_blocks_wrong_numbers():
    sources = build_source_registry(_lead(), _enrichment(), _RESEARCH)
    # Same words as the funding article, but the amount is wrong
    match = match_claim("Acme announced a $50M Series A round.", sources)
    assert match["status"] == "unverified"


def test_enrichment_backed_claim_verifies():
    sources = build_source_registry(_lead(), _enrichment(), None)
    match = match_claim("Acme is in the SaaS industry with a company size of 50-200 employees.", sources)
    assert match["status"] == "verified"
    assert match["source_kind"] == "enrichment"


def test_no_sources_means_unverified():
    match = match_claim("Acme raised $12M recently.", [])
    assert match["status"] == "unverified"
    assert match["source_id"] is None


# ---------------------------------------------------------------------------
# End-to-end report
# ---------------------------------------------------------------------------

def test_ground_email_report_shape():
    report = ground_email(
        "Congrats on the $12M round",
        "Hi Jane,\n\nI saw Acme announced a $12M Series A. "
        "We doubled output for 500 customers last year.\n\nBest,\nSam",
        lead=_lead(), enrichment=_enrichment(), research=_RESEARCH,
    )
    assert report["verified"] >= 1
    assert report["unverified"] >= 1
    assert report["verified"] + report["unverified"] == len(report["claims"])
    assert 0.0 <= report["grounding_score"] <= 1.0
    statuses = {c["status"] for c in report["claims"]}
    assert statuses <= {"verified", "unverified"}


def test_ground_email_with_no_claims_scores_one():
    report = ground_email("Hello", "Hi Jane,\n\nBest,\nSam")
    assert report["claims"] == []
    assert report["grounding_score"] == 1.0


def test_ground_email_never_raises():
    # A lead object whose attribute access explodes must not break outreach
    class Exploding:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    report = ground_email("s", "b", lead=Exploding())
    assert report["grounding_score"] is None
    assert "error" in report


# ---------------------------------------------------------------------------
# Agent + API wiring
# ---------------------------------------------------------------------------

def _run_agent(db, lead, research=None):
    from app.agents.outreach_agent import OutreachAgent
    agent = OutreachAgent.__new__(OutreachAgent)  # skip LLM client init
    agent._ai = None
    agent._judge = None

    fake_quality = {"overall_score": 0.9, "issues": [], "improvement_hint": ""}
    with patch.object(
        OutreachAgent, "_personalise_with_judge",
        return_value=("Congrats on the $12M Series A", "Hi Jane,\n\nI saw Acme announced a $12M Series A round.\n\nBest,\nSam", fake_quality),
    ), patch("app.config.settings.SMTP_HOST", ""):
        return agent.run(db, lead.id, {"research": research or {}})


def test_agent_stores_grounding_on_each_email(test_db):
    lead = _lead()
    test_db.add(lead)
    test_db.commit()

    _run_agent(test_db, lead, research=_RESEARCH)

    emails = test_db.query(OutreachEmail).filter_by(lead_id=lead.id).all()
    assert emails
    for e in emails:
        assert e.claims is not None
        assert "grounding_score" in e.claims
        # The mocked draft cites the $12M round, which research supports
        assert e.claims["verified"] >= 1


def test_agent_recovers_research_from_event_log(test_db):
    from app.database import crud
    lead = _lead()
    test_db.add(lead)
    test_db.commit()
    crud.append_lead_event(
        test_db, lead.id, "pipeline.research.complete",
        payload=_RESEARCH, agent_name="research",
    )

    _run_agent(test_db, lead, research={})  # nothing passed in state

    email = test_db.query(OutreachEmail).filter_by(lead_id=lead.id, step_number=1).first()
    assert email.claims["verified"] >= 1
    assert any(c["source_kind"] == "web_search" for c in email.claims["claims"])


def test_approval_queue_returns_claims(client, test_db):
    from app.services.tenancy import get_default_org

    client.post("/auth/register", json={"email": "admin@test.com", "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": "admin@test.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    lead = _lead(org_id=get_default_org(test_db).id)
    test_db.add(lead)
    test_db.commit()
    email = OutreachEmail(
        lead_id=lead.id, step_number=1, subject="s", body="b",
        status="pending_approval",
        claims={"claims": [{"text": "x", "status": "unverified"}], "verified": 0,
                "unverified": 1, "grounding_score": 0.0, "sources": []},
    )
    test_db.add(email)
    test_db.commit()

    resp = client.get("/outreach/approvals", headers=headers)
    assert resp.status_code == 200
    emails = resp.json()["emails"]
    assert len(emails) == 1
    assert emails[0]["claims"]["unverified"] == 1
