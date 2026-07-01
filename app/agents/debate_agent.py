"""
Debate/Critique Multi-Agent BANT Verdict

Replaces the single AnalysisAgent with a three-agent debate to produce more
accurate and confident qualification verdicts:

  1. AdvocateAgent  — argues FOR qualification; seeks best-case BANT scores
  2. CriticAgent    — argues AGAINST qualification; seeks red flags and disqualifiers
  3. SynthesisAgent — reads both arguments and produces a confidence-weighted verdict

Why this beats a single agent:
  - A single agent tends to rationalise the first verdict it reaches (anchoring bias)
  - Forcing adversarial perspectives surfaces ambiguity in borderline leads
  - The synthesiser's confidence_score reflects genuine disagreement between agents
  - Contested dimensions are flagged for human review

The DebateAgent uses name="analysis" so it is a drop-in replacement in the
LangGraph pipeline — the graph node and downstream nodes are unchanged.
"""

import json
import logging
import time

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.database import crud
from app.services.providers import get_ai_client
from app.config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Guardrails (same rules as AnalysisAgent — enforced after synthesis)
# ---------------------------------------------------------------------------

def _apply_bant_guardrails(verdict: str, bant_scores: dict, overall_score: float) -> tuple[str, str]:
    authority = bant_scores.get("authority", 0.5)
    need = bant_scores.get("need", 0.5)

    if verdict == "Hot":
        if authority < 0.6:
            return "Warm", "authority_too_low"
        if need < 0.7:
            return "Warm", "need_too_low"
        if overall_score < 0.75:
            return "Warm", "overall_score_contradicts_hot"

    if verdict == "Warm":
        if authority < 0.4 and need < 0.4:
            return "Cold", "authority_and_need_both_low"

    if verdict == "Hot" and overall_score < 0.65:
        return "Warm", "overall_score_vs_verdict_mismatch"
    if verdict == "Cold" and overall_score > 0.7:
        return "Warm", "overall_score_vs_verdict_mismatch"

    return verdict, ""


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_ICP_JSON_TEMPLATE = """{{
  "min_employees": {min_size},
  "max_employees": {max_size},
  "target_industries": {industries},
  "min_seniority": "{min_seniority}"
}}"""

_ADVOCATE_PROMPT = """You are a revenue-focused SDR making the strongest possible case for qualifying this lead.

ICP (Ideal Customer Profile):
{icp_json}

Lead + Research Profile:
{profile_json}

Your task: Score this lead on BANT and argue FOR qualification.
Look for the most favourable interpretation of every signal:
  - Budget: largest plausible estimate given company size, funding, and revenue signals
  - Authority: highest plausible seniority or influence from the job title
  - Need: strongest product-market fit signals from industry and role
  - Timeline: fastest plausible buying cycle given growth stage and urgency signals

Score each BANT dimension (0.0–1.0). Suggest a verdict (Hot/Warm/Cold).

Respond with ONLY valid JSON:
{{
  "bant_scores": {{"budget": 0.8, "authority": 0.75, "need": 0.85, "timeline": 0.65}},
  "overall_score": 0.76,
  "verdict": "Hot",
  "reasoning": "VP Engineering at a Series B SaaS — clear decision-making authority and strong product fit..."
}}"""

_CRITIC_PROMPT = """You are a skeptical SDR looking for every reason NOT to qualify this lead.

ICP (Ideal Customer Profile):
{icp_json}

Lead + Research Profile:
{profile_json}

Your task: Score this lead on BANT and argue AGAINST qualification.
Look for the most conservative interpretation of every signal:
  - Budget: smallest plausible estimate; flag pre-revenue or bootstrapped signals
  - Authority: lowest plausible purchasing power; flag IC or director-level needing approval
  - Need: weakest product-market fit; flag wrong industry, non-tech companies, poor stack fit
  - Timeline: slowest plausible cycle; flag enterprise procurement, no urgency, mature stable company

Score each BANT dimension (0.0–1.0). Suggest a verdict (Hot/Warm/Cold).

Respond with ONLY valid JSON:
{{
  "bant_scores": {{"budget": 0.3, "authority": 0.45, "need": 0.55, "timeline": 0.25}},
  "overall_score": 0.39,
  "verdict": "Cold",
  "reasoning": "Seed-stage startup, unclear budget, manager-level title needs VP approval..."
}}"""

_SYNTHESIS_PROMPT = """You are a senior sales manager adjudicating a qualification debate.

Lead Profile:
{profile_json}

Advocate's argument (argues FOR qualification):
{advocate_json}

Critic's argument (argues AGAINST qualification):
{critic_json}

Your task:
1. For each BANT dimension, determine the most accurate score based on concrete evidence.
   Give more weight to arguments backed by specific facts (job title, headcount, funding round,
   industry keyword) than to speculative ones.
2. Note which dimensions have high disagreement (gap > 0.35) — these should be flagged.
3. Produce a final verdict and confidence_score.

Confidence score:
  0.90–1.0  — both agents largely agree, strong evidence
  0.70–0.89 — minor disagreements, one side clearly stronger
  0.50–0.69 — significant disagreement, evidence is ambiguous
  0.30–0.49 — major conflict, outcome is uncertain
  <0.30     — contradictory evidence, do not rely on this verdict alone

Respond with ONLY valid JSON:
{{
  "bant_scores": {{"budget": 0.6, "authority": 0.65, "need": 0.72, "timeline": 0.45}},
  "overall_score": 0.605,
  "verdict": "Warm",
  "confidence_score": 0.74,
  "reasoning": "Advocate's authority case is stronger — VP title is confirmed. Critic's budget concern is valid for seed stage. Synthesis: Warm with medium confidence.",
  "debate_summary": "Advocate emphasised VP seniority and SaaS market fit. Critic flagged seed-stage budget risk and uncertain timeline. Synthesis settles on Warm.",
  "contested_dimensions": ["budget", "timeline"],
  "flags": []
}}

Rules:
- verdict must be exactly: Hot, Warm, or Cold
- confidence_score must be a float 0.0–1.0
- contested_dimensions lists BANT keys where advocate/critic gap > 0.35
- flags lists any structural disqualifiers found (e.g. "wrong_industry", "too_junior")"""


# ---------------------------------------------------------------------------
# DebateAgent
# ---------------------------------------------------------------------------

def _default_bant() -> dict:
    return {"budget": 0.5, "authority": 0.5, "need": 0.5, "timeline": 0.5}


def _set_defaults(parsed: dict) -> None:
    parsed.setdefault("bant_scores", _default_bant())
    parsed.setdefault("overall_score", 0.5)
    parsed.setdefault("verdict", "Cold")
    parsed.setdefault("reasoning", "")


class DebateAgent(BaseAgent):
    """Three-agent adversarial debate producing confident, calibrated BANT verdicts."""

    name = "analysis"

    def __init__(self):
        self._ai = get_ai_client()

    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        profile_json = json.dumps(input_data, indent=2)
        icp_json = _ICP_JSON_TEMPLATE.format(
            min_size=settings.ICP_MIN_COMPANY_SIZE,
            max_size=settings.ICP_MAX_COMPANY_SIZE,
            industries=json.dumps(list(settings.icp_industries)),
            min_seniority=settings.ICP_MIN_SENIORITY,
        )

        # ── Step 1: Advocate ────────────────────────────────────────────────
        advocate = self._call_agent("advocate", _ADVOCATE_PROMPT.format(
            icp_json=icp_json, profile_json=profile_json,
        ))
        _set_defaults(advocate)
        log.info(f"[debate] advocate verdict={advocate['verdict']} score={advocate['overall_score']:.2f}")

        # ── Step 2: Critic ──────────────────────────────────────────────────
        critic = self._call_agent("critic", _CRITIC_PROMPT.format(
            icp_json=icp_json, profile_json=profile_json,
        ))
        _set_defaults(critic)
        log.info(f"[debate] critic verdict={critic['verdict']} score={critic['overall_score']:.2f}")

        # ── Step 3: Synthesis ───────────────────────────────────────────────
        synthesis = self._call_agent("synthesis", _SYNTHESIS_PROMPT.format(
            profile_json=profile_json,
            advocate_json=json.dumps(advocate, indent=2),
            critic_json=json.dumps(critic, indent=2),
        ))
        synthesis.setdefault("bant_scores", _default_bant())
        synthesis.setdefault("overall_score", 0.5)
        synthesis.setdefault("verdict", "Cold")
        synthesis.setdefault("confidence_score", 0.6)
        synthesis.setdefault("reasoning", "")
        synthesis.setdefault("debate_summary", "")
        synthesis.setdefault("contested_dimensions", [])
        synthesis.setdefault("flags", [])

        log.info(
            f"[debate] synthesis verdict={synthesis['verdict']} "
            f"confidence={synthesis['confidence_score']:.2f} "
            f"contested={synthesis['contested_dimensions']}"
        )

        # ── Guardrails ──────────────────────────────────────────────────────
        bant_scores = synthesis["bant_scores"]
        guarded_verdict, guardrail_flag = _apply_bant_guardrails(
            synthesis["verdict"], bant_scores, synthesis["overall_score"]
        )

        flags = list(synthesis["flags"])
        if guardrail_flag:
            flags.append(guardrail_flag)

        # ── Persist verdict ─────────────────────────────────────────────────
        verdict_data = {
            "analysis_verdict": guarded_verdict,
            "analysis_reasoning": synthesis["reasoning"],
            "bant_scores": bant_scores,
            "icp_match": synthesis["overall_score"] >= 0.5,
            "flags": flags,
            "debate_transcript": {
                "advocate": {
                    "bant_scores": advocate["bant_scores"],
                    "overall_score": advocate["overall_score"],
                    "verdict": advocate["verdict"],
                    "reasoning": advocate["reasoning"],
                },
                "critic": {
                    "bant_scores": critic["bant_scores"],
                    "overall_score": critic["overall_score"],
                    "verdict": critic["verdict"],
                    "reasoning": critic["reasoning"],
                },
                "synthesis_reasoning": synthesis["debate_summary"],
                "contested_dimensions": synthesis["contested_dimensions"],
                "confidence_score": synthesis["confidence_score"],
            },
        }

        enrichment_id = input_data.get("enrichment_id")
        # create_verdict accepts **data, which now includes debate_transcript
        verdict_obj = crud.create_verdict(db, lead_id, enrichment_id, {
            k: v for k, v in verdict_data.items()
        })

        result = {
            "analysis_verdict": guarded_verdict,
            "analysis_reasoning": synthesis["reasoning"],
            "bant_scores": bant_scores,
            "icp_match": verdict_data["icp_match"],
            "flags": flags,
            "verdict_id": verdict_obj.id,
            "confidence_score": synthesis["confidence_score"],
            "debate_transcript": verdict_data["debate_transcript"],
        }
        return result

    def _call_agent(self, role: str, prompt: str, max_attempts: int = 3) -> dict:
        last_error = None
        for attempt in range(max_attempts):
            try:
                raw = self._ai.generate(prompt)
                return self._parse_json(raw)
            except Exception as e:
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
        log.warning(f"[debate] {role} agent failed after {max_attempts} attempts: {last_error}")
        return {}
