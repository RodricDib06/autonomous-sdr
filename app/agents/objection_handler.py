"""
Objection Handler & Sentiment Gate

Two capabilities in one agent since they share a single LLM call on every
inbound reply — adding a second call for sentiment would double latency.

Objection classification:
  price           — too expensive, budget constraints
  timing          — not right now, come back later
  wrong_person    — not my department, talk to X instead
  not_interested  — no thanks, unsubscribe, stop emailing
  competitor      — already using Y, happy with our current solution
  info_request    — send more info, how does this work, case study
  positive        — sounds interesting, let's chat, book a call
  other           — anything not matching the above

Each type maps to a specialized reply strategy (sub-prompt). The strategy
instructs the agent on tone, content, and call-to-action for that objection.

Sentiment classification:
  positive    — enthusiastic, interested, warm
  neutral     — matter-of-fact, polite but non-committal
  frustrated  — impatient, annoyed, dismissive (triggers human review flag)
  angry       — hostile, explicitly rude (triggers immediate human handoff)
  confused    — uncertain about what was sent, questions the context

When sentiment is frustrated or angry, `needs_human=True` is returned and
the ConversationalAgent skips reply generation — a human SDR takes over.
"""

import logging
from app.agents.base import BaseAgent
from app.services.providers import get_ai_client

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Objection-specific reply strategies
# ---------------------------------------------------------------------------

_STRATEGIES: dict[str, str] = {
    "price": (
        "Focus on ROI and value, not the price. Ask about the cost of NOT solving the problem. "
        "Offer to share a quick case study showing measurable results. "
        "Do NOT discount or apologise for the price."
    ),
    "timing": (
        "Acknowledge the timing. Ask what would need to change for this to be relevant. "
        "Offer a specific future date: 'Would it make sense to reconnect in Q3?' "
        "Keep the door open with a concrete next step."
    ),
    "wrong_person": (
        "Apologise for the misdirect. Ask who the right person is: "
        "'Could you point me to the right contact? Happy to reach out to them directly.' "
        "If they name someone, thank them. Do not push for more from this contact."
    ),
    "not_interested": (
        "Respect their decision completely. Close gracefully: "
        "'Totally understand — I'll leave the door open if anything changes.' "
        "Do not try to re-engage. This reply ends the sequence."
    ),
    "competitor": (
        "Do not attack the competitor. Acknowledge their choice, then ask a curious question: "
        "'What do you value most about [competitor]?' This surfaces gaps you might fill. "
        "Only differentiate if they bring up a pain — don't lead with it."
    ),
    "info_request": (
        "Provide a concise, specific value point (not a brochure). "
        "End with a direct CTA: 'Worth a 15-minute call to see if it fits?' "
        "Attach or reference a case study if available."
    ),
    "positive": (
        "Match their energy. Propose a specific time to talk: "
        "'Great to hear! Are you free for 15 minutes this Thursday or Friday?' "
        "Keep it short — they're ready, don't oversell."
    ),
    "other": (
        "Be genuinely helpful and specific. If unclear what they need, ask one clarifying question. "
        "Keep the response under 80 words."
    ),
}

# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """Analyse this inbound reply from a B2B sales prospect.

Lead context:
{lead_context}

Their message:
{message}

Classify the OBJECTION TYPE and SENTIMENT.

Objection types:
  price           — mentions cost, budget, price, expensive
  timing          — not now, busy, come back later, bad timing
  wrong_person    — wrong contact, talk to X, not my department
  not_interested  — no thanks, not interested, unsubscribe, stop
  competitor      — already using Y, happy with current solution
  info_request    — send more info, how does this work, case study
  positive        — interested, let's chat, book a call
  other           — does not fit any of the above

Sentiment:
  positive    — warm, enthusiastic, engaged
  neutral     — polite but non-committal
  frustrated  — impatient, dismissive, annoyed
  angry       — hostile, rude, explicit frustration
  confused    — questions the context, seems lost

Respond with ONLY valid JSON:
{{
  "objection_type": "timing",
  "sentiment": "neutral",
  "key_phrase": "not the right time",
  "reasoning": "one sentence explaining the classification"
}}"""

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ObjectionHandlerAgent(BaseAgent):
    """
    Classifies an inbound reply's objection type and sentiment, then selects
    the matching reply strategy. Returns:
      - objection_type: str
      - sentiment: str
      - needs_human: bool
      - strategy: str  (the reply instruction for the ConversationalAgent)
      - key_phrase: str
    """

    name = "objection_handler"

    def __init__(self):
        self._ai = get_ai_client()

    def run(self, db, lead_id: str, input_data: dict) -> dict:
        message = input_data.get("message", "")
        lead_context = input_data.get("lead_context", "")
        return self.classify(message=message, lead_context=lead_context)

    def classify(self, message: str, lead_context: str = "") -> dict:
        """Classify objection + sentiment for an inbound message."""
        prompt = _CLASSIFY_PROMPT.format(
            message=message,
            lead_context=lead_context or "No context available",
        )
        try:
            raw = self._ai.generate(prompt)
            result = self._parse_json(raw)
        except Exception as e:
            log.warning(f"[objection] classification failed ({e}) — defaulting to 'other'/'neutral'")
            result = {}

        objection_type = result.get("objection_type", "other")
        sentiment = result.get("sentiment", "neutral")

        # Human handoff triggers
        needs_human = sentiment in ("frustrated", "angry") or objection_type == "not_interested"

        strategy = _STRATEGIES.get(objection_type, _STRATEGIES["other"])

        log.info(
            f"[objection] type={objection_type} sentiment={sentiment} "
            f"needs_human={needs_human}"
        )
        return {
            "objection_type": objection_type,
            "sentiment": sentiment,
            "needs_human": needs_human,
            "strategy": strategy,
            "key_phrase": result.get("key_phrase", ""),
            "reasoning": result.get("reasoning", ""),
        }
