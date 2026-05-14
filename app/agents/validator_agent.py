import json
import time
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.database import crud
from app.services.ollama_client import OllamaClient  # swap for ClaudeClient via app/services/providers.py
from app.schemas.verdict import ValidatedOutput


PROMPT_TEMPLATE = """You are a quality auditor reviewing an AI sales qualification decision.

Lead profile:
{profile_json}

AI qualification verdict:
{verdict_json}

Your job: Validate that the verdict aligns with the BANT scores and lead profile.

Key checks:
1. BANT-Verdict alignment:
   - Hot verdict requires: authority >0.6, need >0.7, overall_score >0.75
   - Warm verdict requires: authority >0.4 or need >0.4, overall_score 0.5-0.75
   - Cold verdict: overall_score <0.5

2. Internal consistency:
   - Are the four BANT scores logically consistent with each other?
   - Does the reasoning justify the scores?

3. ICP match:
   - Does the company size align with the ICP min/max?
   - Is the seniority at least the minimum ICP level?

Assign a confidence_score (0-1):
- 0.9-1.0: verdict clearly correct, all checks pass
- 0.7-0.9: verdict likely correct, minor questions
- 0.5-0.7: verdict plausible but some inconsistencies
- <0.5: verdict has contradictions

If the verdict fails core checks, downgrade: Hot→Warm, Warm→Cold.

Respond with ONLY valid JSON:
{{
  "validated": true,
  "final_verdict": "Hot",
  "confidence_score": 0.88,
  "consistency_check": "VP at SaaS: authority 0.9, need 0.95, timeline 0.8 all support Hot verdict",
  "flags": []
}}

final_verdict must be exactly one of: Hot, Warm, Cold
confidence_score must be a float between 0.0 and 1.0
flags is a list of strings describing any issues found"""


class ValidatorAgent(BaseAgent):
    name = "validator"

    def __init__(self):
        self._ollama = OllamaClient()  # production: replace with get_ai_client() from app.services.providers

    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        profile = {k: v for k, v in input_data.items() if k not in ("verdict_id", "enrichment_id")}
        verdict_fields = {
            "analysis_verdict": input_data.get("analysis_verdict"),
            "reasoning": input_data.get("analysis_reasoning"),
            "bant_scores": input_data.get("bant_scores"),
            "icp_match": input_data.get("icp_match"),
        }

        prompt = PROMPT_TEMPLATE.format(
            profile_json=json.dumps(profile, indent=2),
            verdict_json=json.dumps(verdict_fields, indent=2),
        )

        raw_response = self._call_with_retry(prompt)
        parsed = self._parse_json(raw_response)
        validated = ValidatedOutput(**parsed)

        update_data = {
            "validated": validated.validated,
            "final_verdict": validated.final_verdict,
            "confidence_score": validated.confidence_score,
            "consistency_notes": validated.consistency_check,
            "flags": validated.flags,
        }

        verdict_id = input_data.get("verdict_id")
        if verdict_id:
            crud.update_verdict(db, verdict_id, update_data)

        result = update_data.copy()
        result["original_verdict"] = input_data.get("analysis_verdict")
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

