"""Tests for OutreachAgent: LLM personalisation and template fallback."""
import json
import pytest
from unittest.mock import MagicMock, patch
from app.agents.outreach_agent import OutreachAgent


@pytest.fixture
def agent():
    with patch("app.agents.outreach_agent.get_ai_client") as mock_ai_factory:
        mock_ai = MagicMock()
        mock_ai_factory.return_value = mock_ai
        a = OutreachAgent()
        a._ai = mock_ai
        return a


def _make_lead(name="Jane Doe", email="jane@acme.com", company="Acme Corp"):
    lead = MagicMock()
    lead.name = name
    lead.email = email
    lead.company = company
    return lead


def _make_enrichment(industry="Software", job_title="VP Engineering", seniority="VP", company_size="50-200"):
    enr = MagicMock()
    enr.industry = industry
    enr.job_title = job_title
    enr.seniority = seniority
    enr.company_size = company_size
    return enr


def _profile(agent, lead=None, enrichment=None):
    """Build a profile dict via the agent helper (mirrors what the agent does internally)."""
    return agent._build_profile(lead or _make_lead(), enrichment or _make_enrichment())


_STEP = {
    "subject_template": "Quick question about {company}",
    "body_template": "Hi {first_name}, reaching out re: {company} in {industry}. Best, {sender_name}",
}


# ---------------------------------------------------------------------------
# _personalise — successful LLM path
# ---------------------------------------------------------------------------

def test_personalise_uses_llm_response_when_valid(agent):
    llm_response = json.dumps({
        "subject": "AI for Acme's GTM",
        "body": "Hi Jane, love what Acme is doing...",
    })
    agent._ai.generate.return_value = llm_response

    subject, body = agent._personalise(_profile(agent), _STEP)

    assert subject == "AI for Acme's GTM"
    assert "Jane" in body


def test_personalise_strips_markdown_from_llm_response(agent):
    llm_response = f"```json\n{json.dumps({'subject': 'Hi there', 'body': 'Body text'})}\n```"
    agent._ai.generate.return_value = llm_response

    subject, body = agent._personalise(_profile(agent), _STEP)

    assert subject == "Hi there"
    assert body == "Body text"


# ---------------------------------------------------------------------------
# _personalise — fallback when LLM fails
# ---------------------------------------------------------------------------

def test_personalise_falls_back_to_template_on_llm_exception(agent):
    agent._ai.generate.side_effect = RuntimeError("LLM unavailable")

    subject, body = agent._personalise(_profile(agent), _STEP)

    # Template substitution should have filled company
    assert "Acme Corp" in subject
    assert "Jane" in body


def test_personalise_falls_back_on_bad_json(agent):
    agent._ai.generate.return_value = "not valid json at all"

    subject, body = agent._personalise(_profile(agent), _STEP)

    assert "Acme Corp" in subject


def test_personalise_falls_back_on_missing_keys_in_json(agent):
    # Valid JSON but missing 'subject' and 'body' keys
    agent._ai.generate.return_value = json.dumps({"result": "oops"})

    subject, body = agent._personalise(_profile(agent), _STEP)

    # Falls back to template
    assert "Acme Corp" in subject


# ---------------------------------------------------------------------------
# _personalise — enrichment=None fallback
# ---------------------------------------------------------------------------

def test_personalise_handles_no_enrichment(agent):
    agent._ai.generate.side_effect = RuntimeError("skip LLM")

    profile = agent._build_profile(_make_lead(), enrichment=None)
    subject, body = agent._personalise(profile, _STEP)

    assert "Acme Corp" in subject
    assert "your industry" in body


# ---------------------------------------------------------------------------
# _personalise — first_name extraction
# ---------------------------------------------------------------------------

def test_first_name_extracted_correctly(agent):
    agent._ai.generate.side_effect = RuntimeError("skip LLM")
    lead = _make_lead(name="Robert Johnson")
    profile = agent._build_profile(lead, _make_enrichment())

    step = {
        "subject_template": "Hi {first_name}",
        "body_template": "{first_name} at {company}",
    }
    _, body = agent._personalise(profile, step)

    assert "Robert" in body
    assert "Johnson" not in body.split("{")[0]  # template fully rendered


def test_first_name_fallback_when_name_empty(agent):
    agent._ai.generate.side_effect = RuntimeError("skip LLM")
    lead = _make_lead(name="")
    profile = agent._build_profile(lead, _make_enrichment())

    step = {
        "subject_template": "Hi {first_name}",
        "body_template": "Hello {first_name}!",
    }
    _, body = agent._personalise(profile, step)

    assert "there" in body  # default fallback


# ---------------------------------------------------------------------------
# _parse_json — inherited from BaseAgent
# ---------------------------------------------------------------------------

def test_parse_json_clean_json(agent):
    raw = json.dumps({"subject": "S", "body": "B"})
    result = agent._parse_json(raw)
    assert result["subject"] == "S"


def test_parse_json_wrapped_in_markdown(agent):
    raw = "```json\n{\"subject\": \"S\", \"body\": \"B\"}\n```"
    result = agent._parse_json(raw)
    assert result["body"] == "B"


def test_parse_json_raises_on_no_json(agent):
    with pytest.raises(ValueError):
        agent._parse_json("Sorry, I can't help with that.")
