"""Tests for LangGraph routing functions in app.agents.graph."""
import pytest
from app.agents.graph import route_after_validate, route_after_orchestrate_human


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
# route_after_orchestrate_human
# ---------------------------------------------------------------------------

def test_human_handoff_when_in_pipeline():
    state = {"routing": {"pipeline": ["human_handoff"]}}
    assert route_after_orchestrate_human(state) == "human_handoff"


def test_no_human_handoff_goes_to_enrich():
    state = {"routing": {"pipeline": ["outreach", "sync_crm"]}}
    assert route_after_orchestrate_human(state) == "enrich"


def test_empty_pipeline_goes_to_enrich():
    state = {"routing": {"pipeline": []}}
    assert route_after_orchestrate_human(state) == "enrich"


def test_missing_routing_key_goes_to_enrich():
    state = {}
    assert route_after_orchestrate_human(state) == "enrich"
