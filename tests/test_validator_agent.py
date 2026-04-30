import json
import pytest
from unittest.mock import MagicMock, patch
from app.agents.validator_agent import ValidatorAgent
from app.schemas.verdict import ValidatedOutput


@pytest.fixture
def agent():
    return ValidatorAgent()


def make_validator_response(validated=True, verdict="Hot", confidence=0.88, flags=None):
    return json.dumps({
        "validated": validated,
        "final_verdict": verdict,
        "confidence_score": confidence,
        "consistency_check": "Verdict is logically consistent with the enriched profile.",
        "flags": flags or []
    })


def test_parse_json_clean(agent):
    result = agent._parse_json(make_validator_response())
    assert result["validated"] is True
    assert result["final_verdict"] == "Hot"


def test_parse_json_strips_markdown(agent):
    wrapped = f"```json\n{make_validator_response(verdict='Warm')}\n```"
    result = agent._parse_json(wrapped)
    assert result["final_verdict"] == "Warm"


def test_validated_output_confidence_clamped():
    data = json.loads(make_validator_response(confidence=1.5))
    validated = ValidatedOutput(**data)
    assert validated.confidence_score == 1.0


def test_validated_output_with_flags():
    data = json.loads(make_validator_response(
        validated=False,
        verdict="Warm",
        confidence=0.45,
        flags=["company_size_below_icp_minimum"]
    ))
    validated = ValidatedOutput(**data)
    assert validated.validated is False
    assert "company_size_below_icp_minimum" in validated.flags
    assert validated.final_verdict == "Warm"


def test_parse_json_raises_on_no_json(agent):
    with pytest.raises(ValueError):
        agent._parse_json("I cannot validate this verdict at this time.")
