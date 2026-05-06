"""
Tests for DataQualityService
"""
from datetime import datetime, timedelta
import pytest
from app.services.data_quality import DataQualityService
from app.database.models import Lead, Enrichment


@pytest.fixture
def service():
    return DataQualityService()


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------

def test_completeness_base_fields_only(service):
    """Lead with only base fields scores ~50 (no enrichment)."""
    lead = Lead(name="Alice Wong", email="alice@acme.com", company="Acme", source="webhook")
    lead.enrichments = []
    score, breakdown = service.calculate_completeness(lead)
    assert score == 50.0
    assert breakdown["name"] is True
    assert breakdown["email"] is True
    assert breakdown["enrichment_job_title"] is False


def test_completeness_with_enrichment(service):
    """Lead with all base + enrichment fields scores 100."""
    lead = Lead(name="Bob Lee", email="bob@corp.com", company="Corp", source="csv_import")
    enrichment = Enrichment(
        job_title="VP Sales",
        seniority="VP",
        company_size="51-200",
        industry="SaaS",
        revenue_estimate="$5M-$10M",
    )
    lead.enrichments = [enrichment]
    score, breakdown = service.calculate_completeness(lead)
    assert score == 100.0
    assert all(breakdown.values())


def test_completeness_missing_required(service):
    """Missing company reduces score."""
    lead = Lead(name="Eve", email="eve@co.com", company="", source="webhook")
    lead.enrichments = []
    score, _ = service.calculate_completeness(lead)
    assert score < 50.0


def test_completeness_partial_enrichment(service):
    """Partial enrichment produces score between 50 and 100."""
    lead = Lead(name="Dan", email="dan@firm.com", company="Firm", source="api")
    enrichment = Enrichment(job_title="Engineer", seniority="IC")
    lead.enrichments = [enrichment]
    score, _ = service.calculate_completeness(lead)
    assert 50.0 < score < 100.0


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

def test_freshness_very_recent(service):
    """Lead updated today scores 100."""
    lead = Lead(created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    assert service.calculate_freshness_score(lead) == 100.0


def test_freshness_two_weeks_old(service):
    """Lead updated 14 days ago scores 80."""
    lead = Lead(
        created_at=datetime.utcnow() - timedelta(days=14),
        updated_at=datetime.utcnow() - timedelta(days=14),
    )
    assert service.calculate_freshness_score(lead) == 80.0


def test_freshness_old(service):
    """Lead updated 200 days ago scores 10."""
    lead = Lead(
        created_at=datetime.utcnow() - timedelta(days=200),
        updated_at=datetime.utcnow() - timedelta(days=200),
    )
    assert service.calculate_freshness_score(lead) == 10.0


def test_freshness_falls_back_to_created_at(service):
    """When updated_at is None, created_at is used."""
    lead = Lead(created_at=datetime.utcnow(), updated_at=None)
    assert service.calculate_freshness_score(lead) == 100.0


# ---------------------------------------------------------------------------
# Email quality
# ---------------------------------------------------------------------------

def test_email_quality_corporate(service):
    score, label = service.calculate_email_quality_score("alice@acme.com")
    assert score == 90.0
    assert label == "corporate"


def test_email_quality_free(service):
    score, label = service.calculate_email_quality_score("alice@gmail.com")
    assert score == 60.0
    assert label == "free"


def test_email_quality_temporary(service):
    score, label = service.calculate_email_quality_score("x@tempmail.com")
    assert score == 0.0
    assert label == "temporary"


def test_email_quality_invalid(service):
    score, label = service.calculate_email_quality_score("not-an-email")
    assert score == 0.0
    assert label == "invalid"


# ---------------------------------------------------------------------------
# Overall score
# ---------------------------------------------------------------------------

def test_overall_score_structure(service):
    """overall score dict contains all expected keys."""
    lead = Lead(
        name="Sam",
        email="sam@company.com",
        company="Widgets Co",
        source="webhook",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    lead.enrichments = []
    result = service.calculate_overall_score(lead)
    for key in ("completeness_score", "freshness_score", "email_quality_score",
                "email_quality_label", "data_quality_score", "breakdown"):
        assert key in result


def test_overall_score_range(service):
    """Overall score is between 0 and 100."""
    lead = Lead(
        name="Kim",
        email="kim@startup.io",
        company="Startup",
        source="api",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    lead.enrichments = []
    result = service.calculate_overall_score(lead)
    assert 0 <= result["data_quality_score"] <= 100


def test_corporate_email_scores_higher_than_free(service):
    """Corporate email lead should score higher than identical lead with free email."""
    def make_lead(email):
        lead = Lead(
            name="Test User",
            email=email,
            company="Corp",
            source="webhook",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        lead.enrichments = []
        return lead

    corp_score = service.calculate_overall_score(make_lead("user@corp.com"))["data_quality_score"]
    free_score = service.calculate_overall_score(make_lead("user@gmail.com"))["data_quality_score"]
    assert corp_score > free_score
