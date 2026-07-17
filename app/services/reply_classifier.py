"""
Reply intelligence — every inbound reply becomes structured data.

Classification is deterministic-first: keyword rules run before any LLM, so
the reply pipeline works (and stays fast) with no model available, and the
compliance-critical categories never wait on a network call. The LLM is
consulted only when the rules are inconclusive and a client is available.

Categories:
  interested   — positive engagement; the conversational agent may respond
  objection    — subtypes price | competitor | no_need | trust; recorded and
                 aggregated per segment, never auto-argued
  referral     — "talk to X" — extracted contact becomes a new lead
  wrong_person — routed to org-chart traversal
  not_now      — timing; cadence stops and re-engagement is scheduled
  auto_reply   — OOO / vacation autoresponders; must NOT count as a reply
  unsubscribe  — detected upstream by compliance.detect_unsubscribe_intent
                 (kept there: opt-out handling never depends on this module)
  other        — no signal; treated as a generic human reply

Aggregated objections feed the campaign agent's planning prompt — the loop
where what prospects say changes what the agent writes next.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger(__name__)

Category = Literal[
    "interested", "objection", "referral", "wrong_person",
    "not_now", "auto_reply", "other",
]
ObjectionSubtype = Literal["price", "competitor", "no_need", "trust"]

OBJECTION_NEEDS_HUMAN_CONFIDENCE = 0.6
DEFAULT_REENGAGE_DAYS = 90

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Order matters: first match wins. auto_reply outranks everything here
# because an OOO frequently *contains* polite interest phrases.
_RULES: list[tuple[str, str | None, re.Pattern]] = [
    ("auto_reply", None, re.compile(
        r"(out\s+of\s+(the\s+)?office|auto[- ]?reply|automatic\s+reply|on\s+(annual|parental|sick)\s+leave|"
        r"on\s+vacation|currently\s+away|away\s+from\s+(my\s+)?email|will\s+respond\s+when\s+i\s+return|"
        r"limited\s+access\s+to\s+email)", re.IGNORECASE)),
    ("referral", None, re.compile(
        r"(talk\s+to|reach\s+out\s+to|contact|loop\s+in|forward(ed)?\s+(this\s+)?to|"
        r"right\s+person\s+(for\s+this\s+)?(is|would\s+be)|better\s+(person|contact)\s+.{0,20}\bis)", re.IGNORECASE)),
    ("wrong_person", None, re.compile(
        r"(not\s+the\s+right\s+person|don'?t\s+handle|no\s+longer\s+(work|responsible|at)|"
        r"wrong\s+(person|department)|not\s+my\s+(area|department|remit))", re.IGNORECASE)),
    ("not_now", None, re.compile(
        r"(not\s+(right\s+)?now|next\s+(quarter|year|month)|circle\s+back|check\s+back|"
        r"try\s+(me\s+)?again\s+in|bad\s+timing|in\s+q[1-4]|after\s+the\s+summer|"
        r"revisit\s+(this\s+)?(in|later)|too\s+busy\s+(right\s+now|at\s+the\s+moment))", re.IGNORECASE)),
    ("objection", "price", re.compile(
        r"(too\s+expensive|no\s+budget|budget\s+(is\s+)?(frozen|tight|spent)|can'?t\s+afford|"
        r"pricing\s+is\s+(too\s+)?high|cost\s+prohibitive)", re.IGNORECASE)),
    ("objection", "competitor", re.compile(
        r"(we\s+(already\s+)?use|already\s+have\s+a\s+(tool|solution|vendor|provider)|"
        r"happy\s+with\s+(our\s+)?current|existing\s+(solution|vendor|contract))", re.IGNORECASE)),
    ("objection", "no_need", re.compile(
        r"(not\s+a\s+priority|don'?t\s+(need|see\s+the\s+need)|no\s+need|not\s+relevant|"
        r"not\s+(currently\s+)?looking|doesn'?t\s+apply\s+to\s+us)", re.IGNORECASE)),
    ("objection", "trust", re.compile(
        r"(how\s+did\s+you\s+get\s+my|is\s+this\s+spam|sounds\s+like\s+spam|don'?t\s+trust|"
        r"never\s+heard\s+of\s+you)", re.IGNORECASE)),
    ("interested", None, re.compile(
        r"(interested|tell\s+me\s+more|sounds\s+(good|great|interesting)|let'?s\s+(talk|chat|connect)|"
        r"book\s+a\s+(call|demo|meeting)|send\s+(me\s+)?(the\s+)?(details|deck|info)|"
        r"happy\s+to\s+(chat|connect|meet)|what\s+times\s+work)", re.IGNORECASE)),
]

# Referral contact extraction: an email that isn't the replier's, plus an
# optional "talk to <Name>" name grab
_REFERRAL_NAME_RE = re.compile(
    r"(?:talk\s+to|reach\s+out\s+to|contact|right\s+person\s+(?:for\s+this\s+)?(?:is|would\s+be)|loop\s+in)"
    r"\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"
)


class Classification(BaseModel):
    category: Category
    subtype: ObjectionSubtype | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.9)
    method: Literal["keyword", "llm"] = "keyword"
    extracted: dict = Field(default_factory=dict)


_LLM_PROMPT = """Classify this reply to a B2B sales email.

Reply:
\"\"\"{text}\"\"\"

Categories: interested | objection | referral | wrong_person | not_now | auto_reply | other
Objection subtypes (only when category is objection): price | competitor | no_need | trust

Respond with ONLY valid JSON:
{{"category": "...", "subtype": null, "confidence": 0.0-1.0,
  "referral_name": null, "referral_email": null, "resume_in_days": null}}"""


def _extract_referral(text: str, exclude_email: str | None = None) -> dict:
    extracted: dict = {}
    for email in _EMAIL_RE.findall(text or ""):
        if exclude_email and email.lower() == exclude_email.lower():
            continue
        extracted["referral_email"] = email.lower()
        break
    m = _REFERRAL_NAME_RE.search(text or "")
    if m:
        extracted["referral_name"] = m.group(1)
    return extracted


def classify_reply(text: str, ai_client=None, sender_email: str | None = None) -> Classification:
    """
    Deterministic keyword pass first; LLM only when rules are inconclusive
    AND a client was provided. Never raises.
    """
    text = (text or "").strip()
    if not text:
        return Classification(category="other", confidence=0.0)

    for category, subtype, pattern in _RULES:
        if pattern.search(text):
            extracted = (
                _extract_referral(text, exclude_email=sender_email)
                if category == "referral" else {}
            )
            return Classification(
                category=category, subtype=subtype,  # type: ignore[arg-type]
                confidence=0.85, method="keyword", extracted=extracted,
            )

    if ai_client is not None:
        try:
            raw = ai_client.generate(_LLM_PROMPT.format(text=text[:2000]))
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}
            extracted = {}
            if data.get("referral_email"):
                extracted["referral_email"] = str(data["referral_email"]).lower()
            if data.get("referral_name"):
                extracted["referral_name"] = str(data["referral_name"])
            if data.get("resume_in_days"):
                extracted["resume_in_days"] = int(data["resume_in_days"])
            return Classification(
                category=data.get("category", "other"),
                subtype=data.get("subtype"),
                confidence=float(data.get("confidence", 0.5)),
                method="llm",
                extracted=extracted,
            )
        except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as e:
            log.debug(f"[reply-classifier] LLM output unusable: {e}")
        except Exception as e:
            log.debug(f"[reply-classifier] LLM unavailable: {e}")

    return Classification(category="other", confidence=0.3)


# ---------------------------------------------------------------------------
# Objection aggregation — feeds analytics and the campaign planner
# ---------------------------------------------------------------------------

def aggregate_objections(db, org_id: str | None = None, limit_examples: int = 3) -> dict:
    """
    Objection counts by subtype and industry. JSONB filtering is done in
    Python so the same code runs on Postgres and the SQLite test rig; reply
    volumes make this a non-issue.
    """
    from app.database.models import Conversation, Enrichment, Lead

    q = (
        db.query(Conversation, Lead, Enrichment)
        .join(Lead, Conversation.lead_id == Lead.id)
        .outerjoin(Enrichment, Enrichment.lead_id == Lead.id)
        .filter(Conversation.classification.isnot(None))
    )
    if org_id is not None:
        q = q.filter(Lead.org_id == org_id)

    by_subtype: dict[str, int] = {}
    by_industry: dict[str, dict[str, int]] = {}
    examples: dict[str, list] = {}
    total = 0

    for conversation, lead, enrichment in q.all():
        c = conversation.classification or {}
        if c.get("category") != "objection":
            continue
        total += 1
        subtype = c.get("subtype") or "other"
        by_subtype[subtype] = by_subtype.get(subtype, 0) + 1

        industry = (enrichment.industry if enrichment else None) or "unknown"
        by_industry.setdefault(industry, {})
        by_industry[industry][subtype] = by_industry[industry].get(subtype, 0) + 1

        if len(examples.setdefault(subtype, [])) < limit_examples:
            last_message = (conversation.messages or [{}])[-1]
            examples[subtype].append({
                "company": lead.company,
                "industry": industry,
                "text": str(last_message.get("content", ""))[:200],
            })

    top = sorted(by_subtype.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "total_objections": total,
        "by_subtype": by_subtype,
        "by_industry": by_industry,
        "top": [{"subtype": s, "count": n} for s, n in top],
        "examples": examples,
    }
