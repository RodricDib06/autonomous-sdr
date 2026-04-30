import json
import re
import time
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.database import crud
from app.services.ollama_client import OllamaClient
from app.schemas.verdict import ValidatedOutput


PROMPT_TEMPLATE = """You are a quality auditor reviewing an AI sales qualification decision.

Lead profile:
{profile_json}

AI qualification verdict:
{verdict_json}

Your job: Check whether the verdict is logically consistent with the lead profile.

Questions to consider:
- Does the final verdict (Hot/Warm/Cold) align with the enriched profile data?
- Are the BANT scores consistent with each other and with the reasoning?
- Does the company size match the ICP requirements for the given verdict?
- Are there any contradictions (e.g., calling a 3-person company "Hot" when ICP needs 50+ employees)?

Assign a confidence_score from 0.0 to 1.0:
- 0.9-1.0: verdict is clearly correct and well-reasoned
- 0.7-0.9: verdict is likely correct with minor uncertainties
- 0.5-0.7: verdict is plausible but questionable
- Below 0.5: verdict has significant inconsistencies

If the verdict has major contradictions, set validated=false and downgrade the verdict one level (Hot→Warm, Warm→Cold).

Respond with ONLY valid JSON — no markdown, no explanation outside the JSON:
{{
  "validated": true,
  "final_verdict": "Hot",
  "confidence_score": 0.88,
  "consistency_check": "...",
  "flags": []
}}

final_verdict must be exactly one of: Hot, Warm, Cold
confidence_score must be a float between 0.0 and 1.0
flags is a list of strings describing any issues found (empty list if none)"""


class ValidatorAgent(BaseAgent):
    name = "validator"

    def __init__(self):
        self._ollama = OllamaClient()

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

    def _parse_json(self, text: str) -> dict:
        text = re.sub(r"```(?:json)?\s*", "", text).strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
        return json.loads(match.group())
