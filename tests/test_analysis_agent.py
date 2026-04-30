import json
import pytest
from unittest.mock import MagicMock, patch
from app.agents.analysis_agent import AnalysisAgent
from app.schemas.verdict import AnalysisOutput


@pytest.fixture
def agent():
    return AnalysisAgent()


def make_good_response(verdict="Hot"):
    return json.dumps({
        "verdict": verdict,
        "reasoning": "Strong ICP match. VP-level decision maker at a 200-person SaaS company.",
        "bant_scores": {
            "budget": "High",
            "authority": "High",
            "need": "Medium",
            "timeline": "Unknown"
        },
        "icp_match": True
    })


def test_parse_json_clean(agent):
    result = agent._parse_json(make_good_response("Hot"))
    assert result["verdict"] == "Hot"
    assert result["icp_match"] is True


def test_parse_json_strips_markdown(agent):
    wrapped = f"```json\n{make_good_response('Warm')}\n```"
    result = agent._parse_json(wrapped)
    assert result["verdict"] == "Warm"


def test_parse_json_raises_on_no_json(agent):
    with pytest.raises(ValueError):
        agent._parse_json("Sorry, I cannot evaluate this lead.")


def test_analysis_output_validation():
    data = json.loads(make_good_response("Cold"))
    validated = AnalysisOutput(**data)
    assert validated.verdict == "Cold"
    assert validated.bant_scores.budget == "High"


def test_bant_coercion_unknown_value():
    data = {
        "verdict": "Warm",
        "reasoning": "Partial match.",
        "bant_scores": {
            "budget": "Unclear",
            "authority": "High",
            "need": "Medium",
            "timeline": "Soon"
        },
        "icp_match": False
    }
    validated = AnalysisOutput(**data)
    assert validated.bant_scores.budget == "Unknown"
    assert validated.bant_scores.timeline == "Unknown"
    assert validated.bant_scores.authority == "High"
