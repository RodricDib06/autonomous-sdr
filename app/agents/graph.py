"""
LangGraph Multi-Agent Orchestration

Replaces the linear agent chain with a proper state graph where:
  - Each agent is a node with its own typed state slice
  - Edges are conditional — routing decisions are made at runtime
  - Enrichment + intent scoring run before analysis (could be parallel in production)
  - Verdict drives which action agents activate (Hot → booking, Warm → outreach, Cold → end)
  - CRM sync always runs as the final step for qualified leads

Graph topology:
  orchestrate → enrich → score_intent → analyse → validate
                                                       │
                              ┌────────────────────────┤
                              │              │          │
                            Hot           Warm        Cold
                              │              │          │
                           booking       outreach   sync_crm → END
                              │              │
                           outreach      sync_crm → END
                              │
                           sync_crm → END

# PRODUCTION notes:
#   - Replace ThreadPoolExecutor calls inside nodes with async LangGraph nodes
#     (use `async def` nodes and `await asyncio.gather` for true parallel enrichment)
#   - Add a LangSmith tracer for full observability:
#       from langsmith import traceable
#       os.environ["LANGCHAIN_TRACING_V2"] = "true"
#       os.environ["LANGCHAIN_API_KEY"] = "..."
#   - Use LangGraph's built-in checkpointing (SqliteSaver / AsyncPostgresSaver)
#     for durable state — survives worker crashes mid-pipeline:
#       from langgraph.checkpoint.sqlite import SqliteSaver
#       graph = workflow.compile(checkpointer=SqliteSaver.from_conn_string(":memory:"))
"""

import logging
from typing import TypedDict
from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared state — every node reads from and writes to this dict
# ---------------------------------------------------------------------------

class LeadState(TypedDict, total=False):
    lead_id: str
    lead_name: str          # human-readable label for log lines
    routing: dict           # output of OrchestratorAgent
    enrichment: dict        # output of EnrichmentAgent
    intent_score: float     # output of intent_scoring service
    analysis: dict          # output of AnalysisAgent
    validation: dict        # output of ValidatorAgent
    outreach: dict          # output of OutreachAgent
    booking: dict           # output of BookingAgent
    crm: dict               # output of CRM sync
    errors: list            # non-fatal errors accumulated across nodes


# ---------------------------------------------------------------------------
# Node functions — each wraps one existing agent / service
# ---------------------------------------------------------------------------

def _db():
    """Open a fresh DB session for this node call."""
    from app.database.connection import SessionLocal
    return SessionLocal()


def node_orchestrate(state: LeadState) -> LeadState:
    from app.agents.orchestrator_agent import OrchestratorAgent
    from app.database import crud
    db = _db()
    try:
        lead = crud.get_lead(db, state["lead_id"])
        agent = OrchestratorAgent()
        result = agent._timed_run(db, state["lead_id"], {})
        log.info(f"[graph/orchestrate] {state['lead_id'][:8]} → action={result['action']}")
        return {**state, "routing": result, "lead_name": lead.name if lead else state["lead_id"]}
    finally:
        db.close()


def node_enrich(state: LeadState) -> LeadState:
    from app.agents.enrichment_agent import EnrichmentAgent
    from app.database import crud
    db = _db()
    try:
        lead = crud.get_lead(db, state["lead_id"])
        agent = EnrichmentAgent()
        result = agent._timed_run(db, state["lead_id"], {
            "email": lead.email, "company": lead.company,
        })
        log.info(f"[graph/enrich] {state['lead_name']} → {result.get('industry')} / {result.get('seniority')}")
        return {**state, "enrichment": result}
    except Exception as e:
        log.error(f"[graph/enrich] {state['lead_name']} failed: {e}")
        return {**state, "enrichment": {}, "errors": state.get("errors", []) + [f"enrich: {e}"]}
    finally:
        db.close()


def node_score_intent(state: LeadState) -> LeadState:
    from app.services.intent_scoring import compute_intent_score
    from app.database import crud
    from app.database.models import Enrichment, Verdict
    db = _db()
    try:
        lead = crud.get_lead(db, state["lead_id"])
        enrichment = db.query(Enrichment).filter(Enrichment.lead_id == state["lead_id"]).first()
        verdict = db.query(Verdict).filter(Verdict.lead_id == state["lead_id"]).first()
        score = compute_intent_score(db, lead, enrichment, verdict)
        log.info(f"[graph/intent] {state['lead_name']} → score={score}")
        return {**state, "intent_score": score}
    except Exception as e:
        log.error(f"[graph/intent] {state['lead_name']} failed: {e}")
        return {**state, "intent_score": 0.0, "errors": state.get("errors", []) + [f"intent: {e}"]}
    finally:
        db.close()


def node_analyse(state: LeadState) -> LeadState:
    from app.agents.analysis_agent import AnalysisAgent
    db = _db()
    try:
        agent = AnalysisAgent()
        result = agent._timed_run(db, state["lead_id"], state.get("enrichment", {}))
        log.info(f"[graph/analyse] {state['lead_name']} → verdict={result.get('analysis_verdict')}")
        return {**state, "analysis": result}
    except Exception as e:
        log.error(f"[graph/analyse] {state['lead_name']} failed: {e}")
        return {**state, "analysis": {"analysis_verdict": "Cold"}, "errors": state.get("errors", []) + [f"analyse: {e}"]}
    finally:
        db.close()


def node_validate(state: LeadState) -> LeadState:
    from app.agents.validator_agent import ValidatorAgent
    db = _db()
    try:
        agent = ValidatorAgent()
        combined = {**state.get("enrichment", {}), **state.get("analysis", {})}
        result = agent._timed_run(db, state["lead_id"], combined)
        log.info(
            f"[graph/validate] {state['lead_name']} → "
            f"final={result.get('final_verdict')} confidence={result.get('confidence_score', 0):.2f}"
        )
        return {**state, "validation": result}
    except Exception as e:
        log.error(f"[graph/validate] {state['lead_name']} failed: {e}")
        fallback_verdict = state.get("analysis", {}).get("analysis_verdict", "Cold")
        return {**state, "validation": {"final_verdict": fallback_verdict, "confidence_score": 0.5},
                "errors": state.get("errors", []) + [f"validate: {e}"]}
    finally:
        db.close()


def node_booking(state: LeadState) -> LeadState:
    from app.agents.booking_agent import BookingAgent
    db = _db()
    try:
        agent = BookingAgent()
        result = agent._timed_run(db, state["lead_id"], {})
        log.info(f"[graph/booking] {state['lead_name']} → {result.get('status')}")
        return {**state, "booking": result}
    except Exception as e:
        log.error(f"[graph/booking] {state['lead_name']} failed: {e}")
        return {**state, "booking": {"status": "error"}, "errors": state.get("errors", []) + [f"booking: {e}"]}
    finally:
        db.close()


def node_outreach(state: LeadState) -> LeadState:
    from app.agents.outreach_agent import OutreachAgent
    db = _db()
    try:
        agent = OutreachAgent()
        result = agent._timed_run(db, state["lead_id"], {})
        log.info(f"[graph/outreach] {state['lead_name']} → {result.get('status')}")
        return {**state, "outreach": result}
    except Exception as e:
        log.error(f"[graph/outreach] {state['lead_name']} failed: {e}")
        return {**state, "outreach": {"status": "error"}, "errors": state.get("errors", []) + [f"outreach: {e}"]}
    finally:
        db.close()


def node_sync_crm(state: LeadState) -> LeadState:
    from app.services.crm_sync import sync_lead_to_crm
    from app.services.data_quality import DataQualityService
    from app.database import crud
    db = _db()
    try:
        # Score data quality as a final step
        lead = crud.get_lead(db, state["lead_id"])
        if lead:
            db.refresh(lead)
            DataQualityService().update_lead_quality(db, lead)
        crud.update_lead_status(db, state["lead_id"], "complete")

        crm_result = sync_lead_to_crm(db, state["lead_id"])

        # Slack alert for Hot leads
        _maybe_notify_slack(db, state, lead)

        log.info(f"[graph/crm_sync] {state['lead_name']} → crm={crm_result.get('crm')} status={crm_result.get('status')}")
        return {**state, "crm": crm_result}
    except Exception as e:
        log.error(f"[graph/crm_sync] {state['lead_name']} failed: {e}")
        return {**state, "crm": {"status": "error"}, "errors": state.get("errors", []) + [f"crm: {e}"]}
    finally:
        db.close()


def node_human_handoff(state: LeadState) -> LeadState:
    """Emit a Slack alert for leads that need human review (unknown source etc.)."""
    from app.services.slack_notifier import SlackNotifier
    from app.config import settings
    notifier = SlackNotifier(settings.SLACK_WEBHOOK_URL)
    if notifier.enabled:
        notifier.notify(
            f":raising_hand: *Human review needed*: {state['lead_name']} "
            f"(source={state.get('routing', {}).get('reason', 'unknown')})"
        )
    log.info(f"[graph/handoff] {state['lead_name']} → flagged for human review")
    return state


# ---------------------------------------------------------------------------
# Conditional routing functions
# ---------------------------------------------------------------------------

def route_after_orchestrate(state: LeadState) -> str:
    action = state.get("routing", {}).get("action", "qualify")
    if action == "qualify":
        return "enrich"
    return END          # duplicate / incomplete / skip


def route_after_validate(state: LeadState) -> str:
    verdict = state.get("validation", {}).get("final_verdict", "Cold")
    pipeline = state.get("routing", {}).get("pipeline", [])

    if verdict == "Hot":
        # Hot leads get a booking attempt; outreach follows regardless
        return "booking" if "booking" in pipeline else "outreach"
    elif verdict == "Warm":
        return "outreach" if "outreach" in pipeline else "sync_crm"
    else:
        return "sync_crm"   # Cold — skip actions, just sync


def route_after_orchestrate_human(state: LeadState) -> str:
    """Secondary router: directs unknown/manual sources to human handoff."""
    pipeline = state.get("routing", {}).get("pipeline", [])
    if "human_handoff" in pipeline:
        return "human_handoff"
    return "enrich"


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    workflow = StateGraph(LeadState)

    # Register nodes
    workflow.add_node("orchestrate",   node_orchestrate)
    workflow.add_node("enrich",        node_enrich)
    workflow.add_node("score_intent",  node_score_intent)
    workflow.add_node("analyse",       node_analyse)
    workflow.add_node("validate",      node_validate)
    workflow.add_node("booking",       node_booking)
    workflow.add_node("outreach",      node_outreach)
    workflow.add_node("sync_crm",      node_sync_crm)
    workflow.add_node("human_handoff", node_human_handoff)

    # Entry point
    workflow.set_entry_point("orchestrate")

    # Orchestrator decides: qualify vs skip vs human handoff
    workflow.add_conditional_edges(
        "orchestrate",
        lambda s: (
            "human_handoff" if "human_handoff" in s.get("routing", {}).get("pipeline", [])
            else route_after_orchestrate(s)
        ),
        {"enrich": "enrich", END: END, "human_handoff": "human_handoff"},
    )

    # Linear qualification chain
    workflow.add_edge("enrich",        "score_intent")
    workflow.add_edge("score_intent",  "analyse")
    workflow.add_edge("analyse",       "validate")

    # Verdict-driven action routing
    workflow.add_conditional_edges(
        "validate",
        route_after_validate,
        {"booking": "booking", "outreach": "outreach", "sync_crm": "sync_crm"},
    )

    # Hot path: booking → outreach → crm
    workflow.add_edge("booking",       "outreach")
    workflow.add_edge("outreach",      "sync_crm")

    # Terminal nodes
    workflow.add_edge("sync_crm",      END)
    workflow.add_edge("human_handoff", END)

    return workflow.compile()


# Module-level compiled graph — import and call graph.invoke({"lead_id": ...})
graph = build_graph()
