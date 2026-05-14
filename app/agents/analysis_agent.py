import json
import logging
import time
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.database import crud
from app.services.ollama_client import OllamaClient  # swap for ClaudeClient via app/services/providers.py
from app.schemas.verdict import AnalysisOutput, BANTScores
from app.config import settings


PROMPT_TEMPLATE = """You are a sales qualification expert. Score this lead on BANT criteria.

ICP (Ideal Customer Profile):
- Company size: {min_size} to {max_size} employees
- Industries: {industries}
- Minimum decision-maker level: {min_seniority}

Lead profile:
{profile_json}

Score each BANT dimension as a probability (0.0 to 1.0) representing how well this lead qualifies:

- Budget (0-1): Does the company have budget for new software?
  * 0.0 = startup with no budget, pre-revenue
  * 0.5 = mid-market with some budget constraints
  * 1.0 = enterprise with unlimited budget
  * Use company size + revenue to estimate

- Authority (0-1): Can this person approve/influence the purchase?
  * 0.0 = junior individual contributor, no purchasing power
  * 0.5 = manager or director, needs approval from above
  * 1.0 = C-suite (CEO/CTO) or VP, sole decision-maker
  * Use job title + seniority to estimate

- Need (0-1): Does this industry + role indicate a real need for B2B software?
  * 0.0 = non-tech industry, poor product fit
  * 0.5 = tangential fit, some use case
  * 1.0 = perfect fit (SaaS/DevTools company, product-market fit)
  * Use industry + role to estimate

- Timeline (0-1): How urgently might they buy?
  * 0.0 = enterprise with 12-month procurement cycles
  * 0.5 = mid-market, 3-6 month decision cycle
  * 1.0 = startup, buys in weeks, fast decision-making
  * Use company size and growth stage to estimate

Calculate overall_score as the average of the four BANT scores.

Based on overall_score, suggest a verdict:
  * 0.75-1.0 → Hot (strong across all dimensions)
  * 0.50-0.75 → Warm (mixed signals, worth pursuing)
  * 0.0-0.50 → Cold (poor fit)

Respond with ONLY valid JSON:
{{
  "verdict": "Hot",
  "reasoning": "VP at $100M SaaS with clear product fit and fast decision cycles",
  "bant_scores": {{
    "budget": 0.85,
    "authority": 0.9,
    "need": 0.95,
    "timeline": 0.8
  }},
  "overall_score": 0.875,
  "icp_match": true
}}

All scores must be floats between 0.0 and 1.0.
Verdict must be exactly one of: Hot, Warm, Cold"""


def _apply_bant_guardrails(verdict: str, bant_scores: dict, overall_score: float) -> tuple[str, str]:
    """Validate verdict against numeric BANT scores. Return (verdict, flag or empty string)."""
    authority = bant_scores.get("authority", 0.5)
    budget = bant_scores.get("budget", 0.5)
    need = bant_scores.get("need", 0.5)

    # Hot requires strong authority (>0.6) AND high need (>0.7)
    if verdict == "Hot":
        if authority < 0.6:
            return "Warm", "authority_too_low"
        if need < 0.7:
            return "Warm", "need_too_low"
        # Also validate against overall score
        if overall_score < 0.75:
            return "Warm", "overall_score_contradicts_hot"

    # Warm requires either decent authority OR decent need (>0.5)
    if verdict == "Warm":
        if authority < 0.4 and need < 0.4:
            return "Cold", "authority_and_need_both_low"

    # If overall_score and verdict severely disagree, flag it
    if verdict == "Hot" and overall_score < 0.65:
        return "Warm", "overall_score_vs_verdict_mismatch"
    if verdict == "Cold" and overall_score > 0.7:
        return "Warm", "overall_score_vs_verdict_mismatch"

    return verdict, ""


class AnalysisAgent(BaseAgent):
    name = "analysis"

    def __init__(self):
        self._ollama = OllamaClient()  # production: replace with get_ai_client() from app.services.providers
        self.logger = logging.getLogger(__name__)

    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        profile_json = json.dumps(input_data, indent=2)
        prompt = PROMPT_TEMPLATE.format(
            min_size=settings.ICP_MIN_COMPANY_SIZE,
            max_size=settings.ICP_MAX_COMPANY_SIZE,
            industries=", ".join(settings.ICP_INDUSTRIES),
            min_seniority=settings.ICP_MIN_SENIORITY,
            profile_json=profile_json,
        )

        raw_response = self._call_with_retry(prompt)
        parsed = self._parse_json(raw_response)
        
        # Ensure required fields are present with defaults
        parsed.setdefault("bant_scores", {
            "budget": 0.5,
            "authority": 0.5,
            "need": 0.5,
            "timeline": 0.5
        })
        parsed.setdefault("overall_score", 0.5)
        parsed.setdefault("icp_match", False)
        parsed.setdefault("reasoning", "Analysis completed")
        
        try:
            validated = AnalysisOutput(**parsed)
        except Exception as e:
            self.logger.error(f"Analysis validation failed for lead {lead_id}: {e}")
            self.logger.error(f"Raw LLM response: {raw_response}")
            self.logger.error(f"Parsed data: {parsed}")
            # Create a fallback response
            validated = AnalysisOutput(
                verdict=parsed.get("verdict", "Cold"),
                reasoning=parsed.get("reasoning", "Analysis failed - using defaults"),
                bant_scores=BANTScores(**parsed.get("bant_scores", {})),
                icp_match=parsed.get("icp_match", False)
            )

        bant_scores = validated.bant_scores.model_dump()
        guarded_verdict, flag = _apply_bant_guardrails(
            validated.verdict,
            bant_scores,
            validated.overall_score
        )

        verdict_data = {
            "analysis_verdict": guarded_verdict,
            "analysis_reasoning": validated.reasoning,
            "bant_scores": bant_scores,
            "overall_score": validated.overall_score,
            "icp_match": validated.icp_match,
        }
        if flag:
            verdict_data["flags"] = [flag]

        enrichment_id = input_data.get("enrichment_id")
        verdict = crud.create_verdict(db, lead_id, enrichment_id, verdict_data)

        result = verdict_data.copy()
        result["verdict_id"] = verdict.id
        return result

    def _call_with_retry(self, prompt: str, max_attempts: int = 3) -> str:
        last_error = None
        for attempt in range(max_attempts):
            try:
                return self._ollama.generate(prompt)
            except Exception as e:
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
        raise last_error

