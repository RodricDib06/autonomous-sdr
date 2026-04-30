import json
import re
import time
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.database import crud
from app.services.ollama_client import OllamaClient
from app.schemas.verdict import AnalysisOutput
from app.config import settings


PROMPT_TEMPLATE = """You are a sales qualification expert. Evaluate this lead against the ICP and BANT criteria below.

ICP (Ideal Customer Profile):
- Company size: {min_size} to {max_size} employees
- Industries: {industries}
- Minimum decision-maker level: {min_seniority}

Lead profile:
{profile_json}

Evaluate each BANT dimension:
- Budget: Does the company revenue/size suggest budget for new tools?
- Authority: Is the job title/seniority level a decision maker?
- Need: Does the industry and role suggest a likely need for B2B software?
- Timeline: Based on company growth stage, how urgent might their need be?

Respond with ONLY valid JSON — no markdown, no explanation outside the JSON:
{{
  "verdict": "Hot",
  "reasoning": "...",
  "bant_scores": {{
    "budget": "High",
    "authority": "High",
    "need": "Medium",
    "timeline": "Unknown"
  }},
  "icp_match": true
}}

verdict must be exactly one of: Hot, Warm, Cold
bant_scores values must be exactly one of: High, Medium, Low, Unknown"""


class AnalysisAgent(BaseAgent):
    name = "analysis"

    def __init__(self):
        self._ollama = OllamaClient()

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
        validated = AnalysisOutput(**parsed)

        verdict_data = {
            "analysis_verdict": validated.verdict,
            "analysis_reasoning": validated.reasoning,
            "bant_scores": validated.bant_scores.model_dump(),
            "icp_match": validated.icp_match,
        }

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

    def _parse_json(self, text: str) -> dict:
        # Strip markdown code fences if present
        text = re.sub(r"```(?:json)?\s*", "", text).strip()
        # Find first JSON object in the response
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
        return json.loads(match.group())
