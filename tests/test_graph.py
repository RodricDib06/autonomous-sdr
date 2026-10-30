"""Tests for LangGraph routing functions in app.agents.graph."""
from types import SimpleNamespace

import pytest

from app.agents import graph as graph_module
from app.agents.graph import route_after_validate
from app.agents.orchestrator_agent import OrchestratorAgent


# ---------------------------------------------------------------------------
# route_after_validate
# ---------------------------------------------------------------------------

def _state(verdict: str, pipeline: list[str]) -> dict:
    return {
        "validation": {"final_verdict": verdict},
        "routing": {"pipeline": pipeline},
    }


def test_hot_with_booking_goes_to_booking():
    state = _state("Hot", ["booking", "outreach", "sync_crm"])
    assert route_after_validate(state) == "booking"


def test_hot_without_booking_falls_back_to_outreach():
    state = _state("Hot", ["outreach", "sync_crm"])
    assert route_after_validate(state) == "outreach"


def test_warm_with_outreach_goes_to_outreach():
    state = _state("Warm", ["outreach", "sync_crm"])
    assert route_after_validate(state) == "outreach"


def test_warm_without_outreach_goes_to_sync_crm():
    state = _state("Warm", ["sync_crm"])
    assert route_after_validate(state) == "sync_crm"


def test_cold_always_goes_to_sync_crm():
    state = _state("Cold", ["booking", "outreach", "sync_crm"])
    assert route_after_validate(state) == "sync_crm"


def test_cold_empty_pipeline_goes_to_sync_crm():
    state = _state("Cold", [])
    assert route_after_validate(state) == "sync_crm"


def test_unknown_verdict_treated_as_cold():
    # Any non-Hot, non-Warm verdict routes to sync_crm
    state = _state("Unqualified", ["outreach"])
    assert route_after_validate(state) == "sync_crm"


def test_missing_validation_key_defaults_cold():
    # Empty state — both keys absent — should not raise
    state = {}
    result = route_after_validate(state)
    assert result == "sync_crm"


# ---------------------------------------------------------------------------
# Human handoff happens after qualification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verdict", ["Hot", "Warm", "Cold"])
def test_handoff_pipeline_routes_to_handoff_after_validate(verdict):
    state = _state(verdict, ["enrichment", "analysis", "validator", "human_handoff"])
    assert route_after_validate(state) == "human_handoff"


def _walk(monkeypatch, pipeline, verdict):
    """Run the compiled graph with stub nodes; return the nodes visited in order."""
    visited = []

    def stub(name, update=None):
        def node(state):
            visited.append(name)
            return {**state, **(update or {})}
        return node

    monkeypatch.setattr(graph_module, "node_orchestrate",
                        stub("orchestrate", {"routing": {"action": "qualify", "pipeline": pipeline}}))
    monkeypatch.setattr(graph_module, "node_validate",
                        stub("validate", {"validation": {"final_verdict": verdict}}))
    for name in ("enrich", "research", "score_intent", "analyse",
                 "booking", "outreach", "sync_crm", "human_handoff"):
        monkeypatch.setattr(graph_module, f"node_{name}", stub(name))

    graph_module.build_graph().invoke({"lead_id": "x", "lead_name": "x", "errors": []})
    return visited


_QUALIFY = ["orchestrate", "enrich", "research", "score_intent", "analyse", "validate"]


def test_handoff_lead_is_qualified_then_completed(monkeypatch):
    visited = _walk(monkeypatch, ["enrichment", "analysis", "validator", "human_handoff"], "Hot")
    assert visited == _QUALIFY + ["human_handoff", "sync_crm"]


def test_hot_inbound_books_then_sequences(monkeypatch):
    visited = _walk(monkeypatch, ["enrichment", "analysis", "validator", "booking", "outreach"], "Hot")
    assert visited == _QUALIFY + ["booking", "outreach", "sync_crm"]


# ---------------------------------------------------------------------------
# Orchestrator: which pipeline each source gets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source,expected_tail", [
    ("website_form", ["booking", "outreach"]),
    ("referral", ["booking", "outreach"]),
    ("csv_import", ["outreach"]),
    ("prospecting:pdl", ["outreach"]),
    ("prospecting:synthetic", ["outreach"]),
    ("org_chart", ["human_handoff"]),     # guessed address — a human checks it
    ("ip_visit", ["human_handoff"]),
    ("manual", ["human_handoff"]),
])
def test_pipeline_by_source(source, expected_tail):
    pipeline = OrchestratorAgent()._decide_pipeline(SimpleNamespace(source=source), {})
    assert pipeline == ["enrichment", "analysis", "validator", *expected_tail]
