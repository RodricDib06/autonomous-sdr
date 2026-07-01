"""
Email Quality Judge

Acts as a quality gate before outreach emails are scheduled. Scores each
LLM-generated email on four dimensions to prevent generic or robotic emails
from reaching leads.

Dimensions (each 0–10):
  specificity     — are company/role-specific details used vs. generic placeholders?
  personalization — does it reference the lead's actual situation?
  relevance       — is the value prop relevant to this lead's profile?
  human_tone      — does it read like a human wrote it?

If overall_score < REJECT_THRESHOLD the judge returns passed=False and an
improvement_hint so OutreachAgent can regenerate with targeted feedback.
Failures are soft: if the judge itself errors, it defaults to passed=True so
the pipeline never blocks on an unavailable LLM.
"""

import json
import logging

from app.agents.base import BaseAgent
from app.services.providers import get_ai_client

log = logging.getLogger(__name__)

REJECT_THRESHOLD = 6.0

_JUDGE_PROMPT = """You are an expert B2B sales coach reviewing a cold outreach email.

Lead profile:
{profile_json}

Email to review:
Subject: {subject}
Body:
{body}

Score this email on 4 dimensions (0–10 each):

specificity (0–10): Are company or role-specific details used?
  0 = completely generic ("Hi there, we help companies like yours")
  10 = highly specific (references the lead's company, recent news, or role challenge)

personalization (0–10): Does it reference the lead's actual situation beyond their name?
  0 = only "Hi {{first_name}}", nothing else personalised
  10 = references role, company stage, industry pain point, or a real signal

relevance (0–10): Is the value proposition relevant to this lead's profile?
  0 = irrelevant value prop for their industry or role
  10 = directly addresses a known pain point for this type of lead

human_tone (0–10): Does it read like a person, not a template?
  0 = obvious placeholders, robotic sentence structure, or "I hope this finds you well"
  10 = conversational, natural, direct

Respond with ONLY valid JSON:
{{
  "specificity": 7,
  "personalization": 6,
  "relevance": 8,
  "human_tone": 7,
  "overall_score": 7.0,
  "issues": ["subject line is still generic"],
  "improvement_hint": ""
}}

Rules:
- overall_score is a float average of the four scores
- issues is a list of short strings describing concrete problems (empty list if none)
- improvement_hint is one sentence describing the single most impactful fix IF overall_score < 6, else empty string
- all dimension scores are integers 0–10"""


class EmailJudgeAgent(BaseAgent):
    """Scores outreach emails for quality before they are scheduled."""

    name = "email_judge"

    def __init__(self):
        self._ai = get_ai_client()

    def run(self, db, lead_id: str, input_data: dict) -> dict:
        return self.score(
            subject=input_data["subject"],
            body=input_data["body"],
            profile=input_data.get("profile", {}),
        )

    def score(self, subject: str, body: str, profile: dict) -> dict:
        """Score an email. Returns a dict with dimension scores and passed=True/False."""
        prompt = _JUDGE_PROMPT.format(
            profile_json=json.dumps(profile, indent=2),
            subject=subject,
            body=body,
        )
        try:
            raw = self._ai.generate(prompt)
            result = self._parse_json(raw)

            # Ensure overall_score is present; compute from dimensions if missing
            dims = [
                result.get("specificity", 5),
                result.get("personalization", 5),
                result.get("relevance", 5),
                result.get("human_tone", 5),
            ]
            result.setdefault("overall_score", sum(dims) / 4)
            result.setdefault("issues", [])
            result.setdefault("improvement_hint", "")

            # Clamp overall to [0, 10]
            result["overall_score"] = max(0.0, min(10.0, float(result["overall_score"])))
            result["passed"] = result["overall_score"] >= REJECT_THRESHOLD

            log.info(
                f"[email_judge] score={result['overall_score']:.1f} "
                f"passed={result['passed']} issues={result['issues']}"
            )
            return result

        except Exception as e:
            log.warning(f"[email_judge] scoring failed ({e}) — defaulting to pass")
            return {
                "specificity": 5,
                "personalization": 5,
                "relevance": 5,
                "human_tone": 5,
                "overall_score": 5.0,
                "issues": [],
                "improvement_hint": "",
                "passed": True,
            }
