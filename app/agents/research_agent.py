"""
ReAct Research Agent — tool-using agent that autonomously decides what to
look up before the BANT analysis node runs.

Architecture (genuine ReAct loop):
  1. LLM receives lead context + tool descriptions
  2. LLM returns JSON: {"thought": "...", "action": "tool_name", "args": {...}}
     OR: {"thought": "...", "action": "done", "summary": "..."}
  3. If tool call → execute → append result → back to step 2
  4. Max 3 iterations to stay within free-tier rate limits

Tools:
  search_web(query)      — Tavily (1 000 free searches/month) or DuckDuckGo
  check_funding(company) — Crunchbase mock / real API if key set
  verify_icp(company, industry, size) — ICP config match check

The agent output (research_notes + research_summary) is stored in LeadState
and passed into the analysis prompt, giving the LLM real research context
instead of just structured enrichment fields.

# PRODUCTION: Replace DuckDuckGo fallback with a Tavily or Exa.ai subscription
# for higher quality, real-time search results. Add LangSmith tracing:
#   from langsmith import traceable
#   @traceable(name="research_agent")
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

log = logging.getLogger(__name__)

_MAX_ITERATIONS = 3

_SYSTEM_PROMPT = """\
You are a B2B sales research agent. Given a lead, decide what to look up to \
find buying signals before we qualify them.

Lead:
{lead_summary}

Enrichment data already collected:
{enrichment_summary}

Available tools:
  search_web        args: {{"query": "<string>"}}
                    Search the web for recent news about this company or person.
  check_funding     args: {{"company": "<string>"}}
                    Look up recent funding rounds, growth signals.
  verify_icp        args: {{"company": "<string>", "industry": "<string>", "size": "<string>"}}
                    Check if this company matches our ideal customer profile.

Respond ONLY with valid JSON in one of these two shapes:

Tool call:
{{"thought": "<your reasoning>", "action": "<tool_name>", "args": {{...}}}}

Final answer (when you have enough context):
{{"thought": "<summary of findings>", "action": "done", "summary": "<1-3 sentence research summary with key buying signals>"}}

Be concise. Stop after 2–3 tool calls maximum.
"""


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _search_web(query: str) -> dict:
    """Search using Tavily (preferred) or DuckDuckGo (free fallback)."""
    if settings.TAVILY_API_KEY:
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=settings.TAVILY_API_KEY)
            resp = client.search(query, max_results=3)
            snippets = [
                {"title": r.get("title", ""), "snippet": r.get("content", "")[:300]}
                for r in resp.get("results", [])
            ]
            return {"source": "tavily", "results": snippets}
        except Exception as e:
            log.warning(f"[research] Tavily failed ({e}), falling back to DuckDuckGo")

    # DuckDuckGo — no API key, no rate limit for demo volumes
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddg:
            for r in ddg.text(query, max_results=3):
                results.append({"title": r.get("title", ""), "snippet": r.get("body", "")[:300]})
        return {"source": "duckduckgo", "results": results}
    except Exception as e:
        log.warning(f"[research] DuckDuckGo failed ({e})")
        return {"source": "unavailable", "results": [], "error": str(e)}


def _check_funding(company: str) -> dict:
    """Proxy to the Crunchbase funding signal service."""
    try:
        from app.services.enrichment.crunchbase import get_funding_signals
        result = get_funding_signals(company, domain=None)
        return {
            "recent_funding": result.get("recent_funding", False),
            "headcount_growth": result.get("headcount_growth_6m", 0),
            "source": result.get("source", "mock"),
        }
    except Exception as e:
        return {"error": str(e)}


def _verify_icp(company: str, industry: str, size: str) -> dict:
    """Check whether this company falls within configured ICP parameters."""
    icp_industries = [i.lower() for i in settings.ICP_INDUSTRIES]
    industry_match = any(kw in industry.lower() for kw in icp_industries)

    size_map = {
        "1-10": 5, "10-50": 30, "50-200": 125, "200-500": 350,
        "500-1000": 750, "1000-2000": 1500, "2000-5000": 3500, "5000+": 7500,
    }
    headcount = size_map.get(size, 0)
    size_match = settings.ICP_MIN_COMPANY_SIZE <= headcount <= settings.ICP_MAX_COMPANY_SIZE

    return {
        "industry_match": industry_match,
        "size_match": size_match,
        "icp_fit": industry_match and size_match,
        "icp_industries": settings.ICP_INDUSTRIES,
        "icp_size_range": f"{settings.ICP_MIN_COMPANY_SIZE}–{settings.ICP_MAX_COMPANY_SIZE}",
    }


_TOOLS = {
    "search_web": _search_web,
    "check_funding": _check_funding,
    "verify_icp": _verify_icp,
}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ResearchAgent:
    """
    Autonomous research agent that uses tool calling to gather buying signals
    before BANT analysis. Implements the ReAct (Reason + Act) pattern.
    """

    def __init__(self):
        from app.services.providers import get_ai_client
        self._ai = get_ai_client()

    def run(self, lead, enrichment) -> dict:
        """
        Run the ReAct loop. Returns:
          {
            "research_notes": [{"tool": ..., "args": ..., "result": ...}, ...],
            "research_summary": "<LLM-generated paragraph>",
            "iterations": int,
          }
        """
        lead_summary = (
            f"Name: {lead.name}\n"
            f"Company: {lead.company}\n"
            f"Email: {lead.email}\n"
            f"Source: {lead.source}\n"
            f"Title: {getattr(lead, 'job_title', '') or ''}"
        )

        enr_summary = "None collected yet."
        if enrichment:
            enr_summary = (
                f"Industry: {enrichment.industry or 'unknown'}\n"
                f"Seniority: {enrichment.seniority or 'unknown'}\n"
                f"Company size: {enrichment.company_size or 'unknown'}\n"
                f"Revenue estimate: {enrichment.revenue_estimate or 'unknown'}\n"
                f"Tech stack: {json.dumps(enrichment.tech_stack or {})}"
            )

        context: list[dict] = []
        summary = ""

        for i in range(_MAX_ITERATIONS):
            prompt = _SYSTEM_PROMPT.format(
                lead_summary=lead_summary,
                enrichment_summary=enr_summary,
            )
            if context:
                tool_history = "\n".join(
                    f"[{c['tool']}({json.dumps(c['args'])})] → {json.dumps(c['result'])[:200]}"
                    for c in context
                )
                prompt += f"\n\nPrevious tool calls:\n{tool_history}\n\nContinue:"

            try:
                raw = self._ai.generate(prompt)
                parsed = self._parse_json(raw)
            except Exception as e:
                log.warning(f"[research] LLM call failed on iteration {i}: {e}")
                break

            action = parsed.get("action", "done")

            if action == "done":
                summary = parsed.get("summary", parsed.get("thought", ""))
                log.info(f"[research] Done after {i+1} iteration(s). Summary: {summary[:80]}...")
                break

            tool_fn = _TOOLS.get(action)
            if not tool_fn:
                log.warning(f"[research] Unknown tool '{action}' — stopping")
                break

            args = parsed.get("args", {})
            try:
                # Emit metric
                try:
                    from app.metrics import research_tool_calls
                    research_tool_calls.labels(tool=action).inc()
                except Exception:
                    pass

                t0 = time.time()
                result = tool_fn(**args)
                elapsed = round((time.time() - t0) * 1000)
                context.append({"tool": action, "args": args, "result": result})
                log.info(f"[research] tool={action} args={args} → {elapsed}ms")
            except Exception as e:
                log.warning(f"[research] Tool '{action}' raised: {e}")
                context.append({"tool": action, "args": args, "result": {"error": str(e)}})

        return {
            "research_notes": context,
            "research_summary": summary,
            "iterations": len(context),
        }

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Extract JSON from LLM output, stripping markdown fences if present."""
        text = raw.strip()
        if "```" in text:
            import re
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if m:
                text = m.group(1).strip()
        # Find first {...} block
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON found in: {text[:200]}")
        return json.loads(text[start:end])
