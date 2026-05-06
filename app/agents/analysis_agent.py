import asyncio
import json
import logging
import time
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.database import crud
from app.services.ollama_client import OllamaClient
from app.schemas.verdict import AnalysisOutput, BANTScores
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
            "budget": "Unknown",
            "authority": "Unknown", 
            "need": "Unknown",
            "timeline": "Unknown"
        })
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
                # Try async call if in async context, fallback to sync
                try:
                    loop = asyncio.get_running_loop()
                    return loop.run_until_complete(self._ollama.generate_async(prompt))
                except RuntimeError:
                    # Not in async context, use sync method
                    return self._ollama.generate(prompt)
            except Exception as e:
                last_error = e
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt)
        raise last_error

