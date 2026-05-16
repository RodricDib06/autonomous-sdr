"""
LangGraph Multi-Agent Orchestration

Graph topology (10 nodes):

  orchestrate → enrich → research → score_intent → analyse → validate
                                                                  │
                              ┌───────────────────────────────────┤
                              │                │                  │
                            Hot             Warm                Cold
                              │                │                  │
                           booking          outreach           sync_crm → END
                              │                │
                           outreach         sync_crm → END
                              │
                           sync_crm → END

New in this revision:
  - research node: ReAct tool-calling agent (search_web / check_funding /
    verify_icp) between enrich and score_intent. Provides real web context
    to the analysis LLM.
  - Redis pub/sub: every node publishes {node, status, duration_ms} to
    channel "pipeline:{lead_id}" so the SSE endpoint can stream live updates.
  - Prometheus metrics: node_duration histogram, llm_calls counter, leads_processed
    counter incremented at sync_crm (terminal node).

All pub/sub and metrics calls are fully wrapped in try/except — a Redis or
Prometheus failure never aborts the pipeline.

# PRODUCTION notes:
#   - Use async def nodes + asyncio.gather for parallel enrich + research
#   - Add LangSmith tracing: LANGCHAIN_TRACING_V2=true, LANGCHAIN_API_KEY=...
#   - Use LangGraph checkpointing (AsyncPostgresSaver) for crash-safe state
"""

import json
import logging
import time
from typing import TypedDict

import structlog
from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Redis pub/sub helper — publishes pipeline events for SSE streaming
# ---------------------------------------------------------------------------

def _publish(lead_id: str, node: str, status: str, **extra) -> None:
    """Fire-and-forget Redis pub/sub publish. Never raises."""
    try:
        from app.services.queue_service import get_redis
        r = get_redis()
        payload = json.dumps({"node": node, "status": status, "lead_id": lead_id, **extra})
        r.publish(f"pipeline:{lead_id}", payload)
    except Exception:
        pass


def _publish_complete(lead_id: str, verdict: str) -> None:
    """Publish the terminal pipeline_complete event."""
    _publish(lead_id, "pipeline", "complete", verdict=verdict)


# ---------------------------------------------------------------------------
# Shared state — every node reads from and writes to this dict
# ---------------------------------------------------------------------------

class LeadState(TypedDict, total=False):
    lead_id: str
    lead_name: str          # human-readable label for log lines
    routing: dict           # output of OrchestratorAgent
    enrichment: dict        # output of EnrichmentAgent
    research: dict          # output of ResearchAgent (tool-calling ReAct)
    intent_score: float     # output of intent_scoring service
    analysis: dict          # output of AnalysisAgent
    validation: dict        # output of ValidatorAgent
    outreach: dict          # output of OutreachAgent
    booking: dict           # output of BookingAgent
    crm: dict               # output of CRM sync
    errors: list            # non-fatal errors accumulated across nodes


# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------

def _db():
    from app.database.connection import SessionLocal
    return SessionLocal()


def _inc_node_duration(node: str, seconds: float) -> None:
    try:
        from app.metrics import node_duration
        node_duration.labels(node=node).observe(seconds)
    except Exception:
        pass


def _inc_pipeline_error(node: str) -> None:
    try:
        from app.metrics import pipeline_errors
        pipeline_errors.labels(node=node).inc()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def node_orchestrate(state: LeadState) -> LeadState:
    from app.agents.orchestrator_agent import OrchestratorAgent
    from app.database import crud
    lead_id = state["lead_id"]
    _publish(lead_id, "orchestrate", "running")
    t0 = time.time()
    db = _db()
    try:
        lead = crud.get_lead(db, lead_id)
        agent = OrchestratorAgent()
        result = agent._timed_run(db, lead_id, {})
        elapsed = time.time() - t0
        _inc_node_duration("orchestrate", elapsed)
        log.info("graph.node.complete", node="orchestrate", lead_id=lead_id[:8], action=result.get("action"), duration_ms=int(elapsed * 1000))
        _publish(lead_id, "orchestrate", "complete", duration_ms=int(elapsed * 1000))
        return {**state, "routing": result, "lead_name": lead.name if lead else lead_id}
    except Exception as e:
        _inc_pipeline_error("orchestrate")
        _publish(lead_id, "orchestrate", "error", error=str(e))
        log.error("graph.node.error", node="orchestrate", lead_id=lead_id, error=str(e))
        raise
    finally:
        db.close()


def node_enrich(state: LeadState) -> LeadState:
    from app.agents.enrichment_agent import EnrichmentAgent
    from app.database import crud
    lead_id = state["lead_id"]
    _publish(lead_id, "enrich", "running")
    t0 = time.time()
    db = _db()
    try:
        lead = crud.get_lead(db, lead_id)
        agent = EnrichmentAgent()
        result = agent._timed_run(db, lead_id, {"email": lead.email, "company": lead.company})
        elapsed = time.time() - t0
        _inc_node_duration("enrich", elapsed)
        try:
            from app.metrics import enrichment_calls
            enrichment_calls.labels(provider=state.get("enrichment_provider", "synthetic")).inc()
        except Exception:
            pass
        log.info("graph.node.complete", node="enrich", lead_id=lead_id[:8], industry=result.get("industry"), duration_ms=int(elapsed * 1000))
        _publish(lead_id, "enrich", "complete", duration_ms=int(elapsed * 1000), industry=result.get("industry", ""))
        return {**state, "enrichment": result}
    except Exception as e:
        elapsed = time.time() - t0
        _inc_node_duration("enrich", elapsed)
        _inc_pipeline_error("enrich")
        _publish(lead_id, "enrich", "error", error=str(e))
        log.error("graph.node.error", node="enrich", lead_id=lead_id, error=str(e))
        return {**state, "enrichment": {}, "errors": state.get("errors", []) + [f"enrich: {e}"]}
    finally:
        db.close()


def node_research(state: LeadState) -> LeadState:
    """
    ReAct tool-calling agent: autonomously decides which tools to call
    (search_web, check_funding, verify_icp) to gather buying signals.
    Output is stored in state['research'] and fed into the analysis prompt.
    Gracefully skips if LLM is unavailable.
    """
    from app.agents.research_agent import ResearchAgent
    from app.database import crud
    from app.database.models import Enrichment
    lead_id = state["lead_id"]
    _publish(lead_id, "research", "running")
    t0 = time.time()
    db = _db()
    try:
        lead = crud.get_lead(db, lead_id)
        enrichment = db.query(Enrichment).filter(Enrichment.lead_id == lead_id).first()
        agent = ResearchAgent()
        result = agent.run(lead, enrichment)
        elapsed = time.time() - t0
        _inc_node_duration("research", elapsed)
        log.info(
            "graph.node.complete",
            node="research",
            lead_id=lead_id[:8],
            iterations=result.get("iterations", 0),
            duration_ms=int(elapsed * 1000),
        )
        _publish(
            lead_id, "research", "complete",
            duration_ms=int(elapsed * 1000),
            iterations=result.get("iterations", 0),
            summary=result.get("research_summary", "")[:120],
        )
        return {**state, "research": result}
    except Exception as e:
        elapsed = time.time() - t0
        _inc_pipeline_error("research")
        _publish(lead_id, "research", "error", error=str(e))
        log.warning("graph.node.skipped", node="research", lead_id=lead_id, reason=str(e))
        # Research is non-critical — never fail the pipeline
        return {**state, "research": {"research_notes": [], "research_summary": "", "iterations": 0},
                "errors": state.get("errors", []) + [f"research: {e}"]}
    finally:
        db.close()


def node_score_intent(state: LeadState) -> LeadState:
    from app.services.intent_scoring import compute_intent_score
    from app.database import crud
    from app.database.models import Enrichment, Verdict
    lead_id = state["lead_id"]
    _publish(lead_id, "score_intent", "running")
    t0 = time.time()
    db = _db()
    try:
        lead = crud.get_lead(db, lead_id)
        enrichment = db.query(Enrichment).filter(Enrichment.lead_id == lead_id).first()
        verdict = db.query(Verdict).filter(Verdict.lead_id == lead_id).first()
        score = compute_intent_score(db, lead, enrichment, verdict)
        elapsed = time.time() - t0
        _inc_node_duration("score_intent", elapsed)
        log.info("graph.node.complete", node="score_intent", lead_id=lead_id[:8], score=score, duration_ms=int(elapsed * 1000))
        _publish(lead_id, "score_intent", "complete", duration_ms=int(elapsed * 1000), score=score)
        return {**state, "intent_score": score}
    except Exception as e:
        elapsed = time.time() - t0
        _inc_pipeline_error("score_intent")
        _publish(lead_id, "score_intent", "error", error=str(e))
        log.error("graph.node.error", node="score_intent", lead_id=lead_id, error=str(e))
        return {**state, "intent_score": 0.0, "errors": state.get("errors", []) + [f"intent: {e}"]}
    finally:
        db.close()


def node_analyse(state: LeadState) -> LeadState:
    from app.agents.analysis_agent import AnalysisAgent
    lead_id = state["lead_id"]
    _publish(lead_id, "analyse", "running")
    t0 = time.time()
    db = _db()
    try:
        agent = AnalysisAgent()
        # Merge enrichment + research summary into context for the LLM
        context = dict(state.get("enrichment", {}))
        research = state.get("research", {})
        if research.get("research_summary"):
            context["research_summary"] = research["research_summary"]
        if research.get("research_notes"):
            context["research_notes"] = research["research_notes"]

        result = agent._timed_run(db, lead_id, context)
        elapsed = time.time() - t0
        _inc_node_duration("analyse", elapsed)
        try:
            from app.metrics import llm_calls
            from app.config import settings
            llm_calls.labels(provider=settings.AI_PROVIDER, agent="analysis").inc()
        except Exception:
            pass
        log.info("graph.node.complete", node="analyse", lead_id=lead_id[:8], verdict=result.get("analysis_verdict"), duration_ms=int(elapsed * 1000))
        _publish(lead_id, "analyse", "complete", duration_ms=int(elapsed * 1000), verdict=result.get("analysis_verdict", ""))
        return {**state, "analysis": result}
    except Exception as e:
        elapsed = time.time() - t0
        _inc_pipeline_error("analyse")
        _publish(lead_id, "analyse", "error", error=str(e))
        log.error("graph.node.error", node="analyse", lead_id=lead_id, error=str(e))
        return {**state, "analysis": {"analysis_verdict": "Cold"}, "errors": state.get("errors", []) + [f"analyse: {e}"]}
    finally:
        db.close()


def node_validate(state: LeadState) -> LeadState:
    from app.agents.validator_agent import ValidatorAgent
    lead_id = state["lead_id"]
    _publish(lead_id, "validate", "running")
    t0 = time.time()
    db = _db()
    try:
        agent = ValidatorAgent()
        combined = {**state.get("enrichment", {}), **state.get("analysis", {})}
        result = agent._timed_run(db, lead_id, combined)
        elapsed = time.time() - t0
        _inc_node_duration("validate", elapsed)
        log.info(
            "graph.node.complete", node="validate", lead_id=lead_id[:8],
            final_verdict=result.get("final_verdict"),
            confidence=round(result.get("confidence_score", 0), 2),
            duration_ms=int(elapsed * 1000),
        )
        _publish(
            lead_id, "validate", "complete",
            duration_ms=int(elapsed * 1000),
            final_verdict=result.get("final_verdict", ""),
            confidence=round(result.get("confidence_score", 0), 2),
        )
        return {**state, "validation": result}
    except Exception as e:
        elapsed = time.time() - t0
        _inc_pipeline_error("validate")
        _publish(lead_id, "validate", "error", error=str(e))
        log.error("graph.node.error", node="validate", lead_id=lead_id, error=str(e))
        fallback = state.get("analysis", {}).get("analysis_verdict", "Cold")
        return {**state, "validation": {"final_verdict": fallback, "confidence_score": 0.5},
                "errors": state.get("errors", []) + [f"validate: {e}"]}
    finally:
        db.close()


def node_booking(state: LeadState) -> LeadState:
    from app.agents.booking_agent import BookingAgent
    lead_id = state["lead_id"]
    _publish(lead_id, "booking", "running")
    t0 = time.time()
    db = _db()
    try:
        agent = BookingAgent()
        result = agent._timed_run(db, lead_id, {})
        elapsed = time.time() - t0
        _inc_node_duration("booking", elapsed)
        log.info("graph.node.complete", node="booking", lead_id=lead_id[:8], status=result.get("status"), duration_ms=int(elapsed * 1000))
        _publish(lead_id, "booking", "complete", duration_ms=int(elapsed * 1000), result_status=result.get("status", ""))
        return {**state, "booking": result}
    except Exception as e:
        elapsed = time.time() - t0
        _inc_pipeline_error("booking")
        _publish(lead_id, "booking", "error", error=str(e))
        log.error("graph.node.error", node="booking", lead_id=lead_id, error=str(e))
        return {**state, "booking": {"status": "error"}, "errors": state.get("errors", []) + [f"booking: {e}"]}
    finally:
        db.close()


def node_outreach(state: LeadState) -> LeadState:
    from app.agents.outreach_agent import OutreachAgent
    lead_id = state["lead_id"]
    _publish(lead_id, "outreach", "running")
    t0 = time.time()
    db = _db()
    try:
        agent = OutreachAgent()
        result = agent._timed_run(db, lead_id, {})
        elapsed = time.time() - t0
        _inc_node_duration("outreach", elapsed)
        try:
            from app.metrics import llm_calls
            from app.config import settings
            llm_calls.labels(provider=settings.AI_PROVIDER, agent="outreach").inc()
        except Exception:
            pass
        log.info("graph.node.complete", node="outreach", lead_id=lead_id[:8], status=result.get("status"), duration_ms=int(elapsed * 1000))
        _publish(lead_id, "outreach", "complete", duration_ms=int(elapsed * 1000), result_status=result.get("status", ""))
        return {**state, "outreach": result}
    except Exception as e:
        elapsed = time.time() - t0
        _inc_pipeline_error("outreach")
        _publish(lead_id, "outreach", "error", error=str(e))
        log.error("graph.node.error", node="outreach", lead_id=lead_id, error=str(e))
        return {**state, "outreach": {"status": "error"}, "errors": state.get("errors", []) + [f"outreach: {e}"]}
    finally:
        db.close()


def node_sync_crm(state: LeadState) -> LeadState:
    from app.services.crm_sync import sync_lead_to_crm
    from app.services.data_quality import DataQualityService
    from app.database import crud
    lead_id = state["lead_id"]
    _publish(lead_id, "sync_crm", "running")
    t0 = time.time()
    db = _db()
    try:
        lead = crud.get_lead(db, lead_id)
        if lead:
            db.refresh(lead)
            DataQualityService().update_lead_quality(db, lead)
        crud.update_lead_status(db, lead_id, "complete")
        crm_result = sync_lead_to_crm(db, lead_id)
        _maybe_notify_slack(db, state, lead)

        elapsed = time.time() - t0
        _inc_node_duration("sync_crm", elapsed)

        verdict = state.get("validation", {}).get("final_verdict", "unknown")
        try:
            from app.metrics import leads_processed
            leads_processed.labels(verdict=verdict).inc()
        except Exception:
            pass

        log.info("graph.node.complete", node="sync_crm", lead_id=lead_id[:8], crm=crm_result.get("crm"), duration_ms=int(elapsed * 1000))
        _publish(lead_id, "sync_crm", "complete", duration_ms=int(elapsed * 1000))
        _publish_complete(lead_id, verdict)
        return {**state, "crm": crm_result}
    except Exception as e:
        elapsed = time.time() - t0
        _inc_pipeline_error("sync_crm")
        _publish(lead_id, "sync_crm", "error", error=str(e))
        _publish_complete(lead_id, "unknown")
        log.error("graph.node.error", node="sync_crm", lead_id=lead_id, error=str(e))
        return {**state, "crm": {"status": "error"}, "errors": state.get("errors", []) + [f"crm: {e}"]}
    finally:
        db.close()


def node_human_handoff(state: LeadState) -> LeadState:
    from app.services.slack_notifier import SlackNotifier
    from app.config import settings
    lead_id = state["lead_id"]
    _publish(lead_id, "human_handoff", "running")
    notifier = SlackNotifier(settings.SLACK_WEBHOOK_URL)
    if notifier.enabled:
        notifier.notify(
            f":raising_hand: *Human review needed*: {state['lead_name']} "
            f"(source={state.get('routing', {}).get('reason', 'unknown')})"
        )
    log.info("graph.node.complete", node="human_handoff", lead_id=lead_id[:8])
    _publish(lead_id, "human_handoff", "complete")
    _publish_complete(lead_id, "handoff")
    return state


# ---------------------------------------------------------------------------
# Slack helper (unchanged)
# ---------------------------------------------------------------------------

def _maybe_notify_slack(db, state: LeadState, lead) -> None:
    verdict = state.get("validation", {}).get("final_verdict", "")
    if verdict != "Hot" or not lead:
        return
    try:
        from app.services.slack_notifier import SlackNotifier
        from app.config import settings
        notifier = SlackNotifier(settings.SLACK_WEBHOOK_URL)
        if notifier.enabled:
            score = state.get("validation", {}).get("confidence_score", 0)
            notifier.notify(
                f":fire: *Hot lead qualified*: {lead.name} @ {lead.company} "
                f"(confidence={score:.0%})"
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Conditional routing (unchanged logic, structlog instrumented)
# ---------------------------------------------------------------------------

def route_after_orchestrate(state: LeadState) -> str:
    action = state.get("routing", {}).get("action", "qualify")
    if action == "qualify":
        return "enrich"
    return END


def route_after_validate(state: LeadState) -> str:
    verdict = state.get("validation", {}).get("final_verdict", "Cold")
    pipeline = state.get("routing", {}).get("pipeline", [])

    if verdict == "Hot":
        return "booking" if "booking" in pipeline else "outreach"
    elif verdict == "Warm":
        return "outreach" if "outreach" in pipeline else "sync_crm"
    else:
        return "sync_crm"


def route_after_orchestrate_human(state: LeadState) -> str:
    pipeline = state.get("routing", {}).get("pipeline", [])
    if "human_handoff" in pipeline:
        return "human_handoff"
    return "enrich"


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    workflow = StateGraph(LeadState)

    workflow.add_node("orchestrate",   node_orchestrate)
    workflow.add_node("enrich",        node_enrich)
    workflow.add_node("research",      node_research)      # NEW: ReAct tool-calling
    workflow.add_node("score_intent",  node_score_intent)
    workflow.add_node("analyse",       node_analyse)
    workflow.add_node("validate",      node_validate)
    workflow.add_node("booking",       node_booking)
    workflow.add_node("outreach",      node_outreach)
    workflow.add_node("sync_crm",      node_sync_crm)
    workflow.add_node("human_handoff", node_human_handoff)

    workflow.set_entry_point("orchestrate")

    workflow.add_conditional_edges(
        "orchestrate",
        lambda s: (
            "human_handoff" if "human_handoff" in s.get("routing", {}).get("pipeline", [])
            else route_after_orchestrate(s)
        ),
        {"enrich": "enrich", END: END, "human_handoff": "human_handoff"},
    )

    # Linear qualification chain — research sits between enrich and score_intent
    workflow.add_edge("enrich",        "research")
    workflow.add_edge("research",      "score_intent")
    workflow.add_edge("score_intent",  "analyse")
    workflow.add_edge("analyse",       "validate")

    workflow.add_conditional_edges(
        "validate",
        route_after_validate,
        {"booking": "booking", "outreach": "outreach", "sync_crm": "sync_crm"},
    )

    workflow.add_edge("booking",       "outreach")
    workflow.add_edge("outreach",      "sync_crm")
    workflow.add_edge("sync_crm",      END)
    workflow.add_edge("human_handoff", END)

    return workflow.compile()


# Module-level compiled graph — import and call graph.invoke({"lead_id": ...})
graph = build_graph()
