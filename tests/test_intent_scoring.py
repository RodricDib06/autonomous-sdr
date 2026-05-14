"""Tests for intent scoring: signal rules, score accumulation, DB persistence."""
import pytest
from unittest.mock import MagicMock, patch, call
from app.services.intent_scoring import compute_intent_score, get_lead_intent_score


def _make_lead(source="inbound_email", email="test@acme.com", company="Acme"):
    lead = MagicMock()
    lead.id = "lead-123"
    lead.source = source
    lead.email = email
    lead.company = company
    return lead


def _make_enrichment(
    seniority="VP",
    company_size="50-200",
    industry="Software",
    revenue_estimate="$100M-$500M",
    tech_stack=None,
):
    enr = MagicMock()
    enr.seniority = seniority
    enr.company_size = company_size
    enr.industry = industry
    enr.revenue_estimate = revenue_estimate
    enr.tech_stack = tech_stack or {"primary": "aws", "secondary": "postgres"}
    return enr


def _make_verdict(need=0.8, authority=0.8, budget=0.8):
    v = MagicMock()
    v.bant_scores = {"need": need, "authority": authority, "budget": budget}
    return v


# ---------------------------------------------------------------------------
# Source signal mapping
# ---------------------------------------------------------------------------

def test_inbound_email_source_adds_signal():
    db = MagicMock()
    lead = _make_lead(source="inbound_email")
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        score = compute_intent_score(db, lead, enrichment=None, verdict=None)
    assert score > 0.0
    db.add.assert_called()
    added_signals = [c.args[0].signal_type for c in db.add.call_args_list]
    assert "inbound_email" in added_signals


def test_unknown_source_adds_no_source_signal():
    db = MagicMock()
    lead = _make_lead(source="unknown_channel")
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        score = compute_intent_score(db, lead, enrichment=None, verdict=None)
    # Score should be 0.0 — no signals triggered
    assert score == 0.0


def test_marketing_ad_source_has_lower_weight_than_inbound():
    db_inbound = MagicMock()
    db_ad = MagicMock()
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        score_inbound = compute_intent_score(db_inbound, _make_lead(source="inbound_email"), None, None)
        score_ad = compute_intent_score(db_ad, _make_lead(source="marketing_ad"), None, None)
    assert score_inbound > score_ad


# ---------------------------------------------------------------------------
# Enrichment signals
# ---------------------------------------------------------------------------

def test_high_seniority_adds_signal():
    db = MagicMock()
    lead = _make_lead(source="website_form")
    enr = _make_enrichment(seniority="VP")
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        score = compute_intent_score(db, lead, enrichment=enr, verdict=None)
    added = [c.args[0].signal_type for c in db.add.call_args_list]
    assert "high_seniority" in added


def test_non_icp_seniority_no_seniority_signal():
    db = MagicMock()
    lead = _make_lead(source="website_form")
    enr = _make_enrichment(seniority="Intern")
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        compute_intent_score(db, lead, enrichment=enr, verdict=None)
    added = [c.args[0].signal_type for c in db.add.call_args_list]
    assert "high_seniority" not in added


def test_high_revenue_trigger():
    db = MagicMock()
    lead = _make_lead()
    enr = _make_enrichment(seniority="Analyst", revenue_estimate="$1B+")
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        compute_intent_score(db, lead, enrichment=enr, verdict=None)
    added = [c.args[0].signal_type for c in db.add.call_args_list]
    assert "high_revenue" in added


def test_tech_stack_aws_triggers_signal():
    db = MagicMock()
    lead = _make_lead()
    enr = _make_enrichment(tech_stack={"infra": "aws"})
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        compute_intent_score(db, lead, enrichment=enr, verdict=None)
    added = [c.args[0].signal_type for c in db.add.call_args_list]
    assert "strong_tech_stack" in added


def test_tech_stack_irrelevant_no_signal():
    db = MagicMock()
    lead = _make_lead(source="marketing_ad")
    enr = _make_enrichment(seniority="Intern", revenue_estimate="<$1M", tech_stack={"crm": "salesforce"}, industry="retail")
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        compute_intent_score(db, lead, enrichment=enr, verdict=None)
    added = [c.args[0].signal_type for c in db.add.call_args_list]
    assert "strong_tech_stack" not in added


# ---------------------------------------------------------------------------
# BANT-derived signals
# ---------------------------------------------------------------------------

def test_high_bant_scores_add_all_three_signals():
    db = MagicMock()
    lead = _make_lead(source="inbound_email")
    verdict = _make_verdict(need=0.9, authority=0.85, budget=0.8)
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        compute_intent_score(db, lead, enrichment=None, verdict=verdict)
    added = [c.args[0].signal_type for c in db.add.call_args_list]
    assert "high_bant_need" in added
    assert "high_bant_authority" in added
    assert "high_bant_budget" in added


def test_low_bant_scores_add_no_bant_signals():
    db = MagicMock()
    lead = _make_lead(source="marketing_ad")
    verdict = _make_verdict(need=0.3, authority=0.4, budget=0.2)
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        compute_intent_score(db, lead, enrichment=None, verdict=verdict)
    added = [c.args[0].signal_type for c in db.add.call_args_list]
    assert "high_bant_need" not in added
    assert "high_bant_authority" not in added
    assert "high_bant_budget" not in added


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------

def test_score_clamped_to_1():
    db = MagicMock()
    lead = _make_lead(source="inbound_email")
    enr = _make_enrichment(seniority="C-Suite", company_size="50-200", revenue_estimate="$1B+")
    verdict = _make_verdict(need=0.95, authority=0.95, budget=0.95)
    with patch("app.services.enrichment.crunchbase.get_funding_signals", return_value={
        "recent_funding": True, "headcount_growth_6m": 0.25, "source": "mock"
    }):
        with patch("app.services.intent_scoring.settings") as mock_settings:
            mock_settings.ICP_MIN_COMPANY_SIZE = 10
            mock_settings.ICP_MAX_COMPANY_SIZE = 500
            mock_settings.ICP_INDUSTRIES = ["software"]
            score = compute_intent_score(db, lead, enrichment=enr, verdict=verdict)
    assert score <= 1.0


def test_db_commit_called_after_signals():
    db = MagicMock()
    lead = _make_lead(source="inbound_email")
    with patch("app.services.enrichment.crunchbase.get_funding_signals", side_effect=Exception("skip")):
        compute_intent_score(db, lead, None, None)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# get_lead_intent_score
# ---------------------------------------------------------------------------

def test_get_lead_intent_score_sums_signals():
    db = MagicMock()
    sig1 = MagicMock()
    sig1.score = 0.30
    sig2 = MagicMock()
    sig2.score = 0.25
    db.query.return_value.filter.return_value.all.return_value = [sig1, sig2]

    score = get_lead_intent_score(db, "lead-123")
    assert score == 0.55


def test_get_lead_intent_score_clamps_at_1():
    db = MagicMock()
    sigs = [MagicMock(score=0.5) for _ in range(5)]  # sum = 2.5
    db.query.return_value.filter.return_value.all.return_value = sigs

    score = get_lead_intent_score(db, "lead-123")
    assert score == 1.0


def test_get_lead_intent_score_no_signals_returns_0():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    score = get_lead_intent_score(db, "lead-abc")
    assert score == 0.0
