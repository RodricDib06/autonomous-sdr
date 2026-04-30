import pytest
from app.services.enrichment.synthetic import SyntheticEnrichmentProvider
from app.schemas.enrichment import EnrichmentOutput


@pytest.fixture
def provider():
    return SyntheticEnrichmentProvider()


def test_known_domain_returns_valid_output(provider):
    result = provider.enrich("sarah.chen@stripe.com", "Stripe")
    validated = EnrichmentOutput(**result)
    assert validated.industry == "FinTech"
    assert validated.confidence >= 0.7
    assert len(validated.tech_stack) >= 1
    assert validated.enrichment_source == "domain_heuristics_v1"


def test_unknown_domain_returns_valid_output(provider):
    result = provider.enrich("john@unknownstartup.com", "Unknown Co")
    validated = EnrichmentOutput(**result)
    assert validated.industry in ["Technology", "SaaS", "AI/ML", "DevTools", "Finance", "Education", "Government", "Non-Profit", "Healthcare"]
    assert 0.0 <= validated.confidence <= 1.0
    assert validated.seniority in ["Junior", "Mid-Level", "Senior", "Manager", "Director", "VP", "C-Suite"]


def test_io_domain_infers_saas(provider):
    result = provider.enrich("alice@someapp.io", "SomeApp")
    assert result["industry"] == "SaaS"


def test_ai_domain_infers_aiml(provider):
    result = provider.enrich("bob@coolai.ai", "CoolAI")
    assert result["industry"] == "AI/ML"


def test_enrichment_has_all_required_fields(provider):
    result = provider.enrich("test@example.com", "Example Inc")
    required_fields = ["job_title", "seniority", "company_size", "industry",
                       "revenue_estimate", "tech_stack", "confidence", "enrichment_source"]
    for field in required_fields:
        assert field in result, f"Missing field: {field}"
