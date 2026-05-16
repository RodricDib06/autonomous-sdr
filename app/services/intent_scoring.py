"""
Buyer Intent Scoring Service

PoC approach: derives an intent score (0.0–1.0) from enrichment data and
ingestion-source signals already in the database. No paid API needed.

Each signal adds a weighted contribution. Final score = clipped sum of weights.

# PRODUCTION replacements (drop-in, same interface):
#   - Bombora: company-level intent via B2B data co-op. REST API.
#       POST https://api.bombora.com/surge/topics?company_domain={domain}
#       Returns topic clusters + surge score per domain.
#       Pricing: ~$2–5k/month. Docs: https://bombora.com/resources/api-documentation/
#
#   - G2 Buyer Intent: detects when target accounts visit G2 product pages.
#       Available via G2 Buyer Intent API (requires G2 profile).
#       Docs: https://documentation.g2.com/docs/buyer-intent-api
#
#   - Clearbit Reveal: de-anonymises website traffic → company domain → intent.
#       GET https://reveal.clearbit.com/v1/companies/find?domain={domain}
#       Pairs well with page-visit tracking via Segment.
#       Docs: https://clearbit.com/docs#reveal
#
#   - 6sense: account-level intent via predictive AI (enterprise, $$$$).
#       REST API — contact sales.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy.orm import Session

from app.database.models import Lead, Enrichment, Verdict, IntentSignal
from app.config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal definitions — each maps to an IntentSignal.signal_type
# ---------------------------------------------------------------------------

@dataclass
class SignalRule:
    signal_type: str
    weight: float          # contribution to total score (0.0–1.0)
    description: str


_RULES: list[SignalRule] = [
    # Source-based signals
    SignalRule("inbound_email",        0.30, "Prospect emailed us first — high intent"),
    SignalRule("linkedin_signal",      0.25, "LinkedIn interaction — explicit interest"),
    SignalRule("event_registration",   0.20, "Registered for webinar/demo"),
    SignalRule("website_form",         0.15, "Filled out a contact form"),
    SignalRule("marketing_ad",         0.05, "Clicked a paid ad — weak intent"),

    # Company-characteristic signals (inferred from enrichment)
    SignalRule("high_seniority",       0.15, "Decision-maker or above"),
    SignalRule("ideal_company_size",   0.12, "Company size in ICP range"),
    SignalRule("icp_industry",         0.12, "Industry matches ICP"),
    SignalRule("strong_tech_stack",    0.08, "Tech stack compatible with product"),
    SignalRule("high_revenue",         0.06, "Revenue suggests budget availability"),

    # BANT-derived signals (from verdict if already scored)
    SignalRule("high_bant_need",       0.10, "BANT need score > 0.7"),
    SignalRule("high_bant_authority",  0.08, "BANT authority score > 0.7"),
    SignalRule("high_bant_budget",     0.06, "BANT budget score > 0.7"),

    # Crunchbase funding signals (free mock / real API via CRUNCHBASE_API_KEY)
    SignalRule("recent_funding",       0.20, "Raised a round in last 6 months — likely buying"),
    SignalRule("headcount_growth",     0.10, "Headcount growing >10% — scaling and spending"),

    # # PRODUCTION: Bombora surge topics detected for this domain
    # SignalRule("bombora_surge",        0.35, "Bombora surge topic match"),
    #
    # # PRODUCTION: G2 competitor comparison page visit
    # SignalRule("g2_intent",            0.30, "Viewed G2 category / competitor page"),
    #
    # # PRODUCTION: Clearbit Reveal — company visited our pricing page
    # SignalRule("pricing_page_visit",   0.25, "Anonymous visitor de-anonymised on pricing page"),
    #
    # # PRODUCTION: Job postings signal (LinkedIn / Greenhouse scrape)
    # SignalRule("hiring_for_role",      0.15, "Actively hiring in a role your product helps with"),
]

_RULE_MAP = {r.signal_type: r for r in _RULES}

# Company size ranges that match ICP
_SENIORITY_HIGH = {"Director", "VP", "C-Suite"}
_SIZE_RANGES_ICP = None   # resolved lazily from settings


def _icp_sizes() -> set[str]:
    global _SIZE_RANGES_ICP
    if _SIZE_RANGES_ICP is None:
        # Build from config min/max — rough mapping to size-range strings
        mn = settings.ICP_MIN_COMPANY_SIZE
        mx = settings.ICP_MAX_COMPANY_SIZE
        all_ranges = [
            ("1-10", 1, 10), ("10-50", 10, 50), ("50-200", 50, 200),
            ("200-500", 200, 500), ("500-1000", 500, 1000),
            ("1000-2000", 1000, 2000), ("2000-5000", 2000, 5000),
            ("5000-10000", 5000, 10000), ("10000+", 10000, 999999),
        ]
        _SIZE_RANGES_ICP = {label for label, lo, hi in all_ranges if lo < mx and hi > mn}
    return _SIZE_RANGES_ICP


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def compute_intent_score(
    db: Session,
    lead: Lead,
    enrichment: Enrichment | None = None,
    verdict: Verdict | None = None,
) -> float:
    """
    Compute a 0.0–1.0 intent score and persist detected signals.

    Returns the final clamped score.
    """
    signals: list[tuple[str, float, str]] = []  # (signal_type, score, source)

    # ── Source signal ────────────────────────────────────────────────────────
    source_signal_map = {
        "inbound_email":   "inbound_email",
        "linkedin_signal": "linkedin_signal",
        "event":           "event_registration",
        "website_form":    "website_form",
        "marketing_ad":    "marketing_ad",
    }
    if lead.source in source_signal_map:
        stype = source_signal_map[lead.source]
        rule = _RULE_MAP.get(stype)
        if rule:
            signals.append((stype, rule.weight, "heuristic"))

    # ── Enrichment signals ────────────────────────────────────────────────────
    if enrichment:
        seniority = enrichment.seniority or ""
        if seniority in _SENIORITY_HIGH:
            signals.append(("high_seniority", _RULE_MAP["high_seniority"].weight, "heuristic"))

        if enrichment.company_size in _icp_sizes():
            signals.append(("ideal_company_size", _RULE_MAP["ideal_company_size"].weight, "heuristic"))

        industry = (enrichment.industry or "").lower()
        icp_industries = [i.lower() for i in settings.icp_industries]
        if any(icp in industry for icp in icp_industries):
            signals.append(("icp_industry", _RULE_MAP["icp_industry"].weight, "heuristic"))

        # Revenue proxy: revenue_estimate string like "$20M-$100M"
        rev = enrichment.revenue_estimate or ""
        if any(marker in rev for marker in ["$100M", "$500M", "$1B", "$5B"]):
            signals.append(("high_revenue", _RULE_MAP["high_revenue"].weight, "heuristic"))

        # Tech stack: does the lead's stack include cloud / devtools?
        stack = enrichment.tech_stack or []
        if isinstance(stack, dict):
            stack_items = list(stack.values())
        else:
            stack_items = stack
        known_tools = set(str(v).lower() for v in stack_items if isinstance(v, str))
        cloud_tools = {"aws", "gcp", "azure", "docker", "kubernetes", "postgres", "redis"}
        if known_tools & cloud_tools:
            signals.append(("strong_tech_stack", _RULE_MAP["strong_tech_stack"].weight, "heuristic"))

    # ── BANT signals ─────────────────────────────────────────────────────────
    if verdict and verdict.bant_scores:
        bant = verdict.bant_scores
        if bant.get("need", 0) > 0.7:
            signals.append(("high_bant_need", _RULE_MAP["high_bant_need"].weight, "heuristic"))
        if bant.get("authority", 0) > 0.7:
            signals.append(("high_bant_authority", _RULE_MAP["high_bant_authority"].weight, "heuristic"))
        if bant.get("budget", 0) > 0.7:
            signals.append(("high_bant_budget", _RULE_MAP["high_bant_budget"].weight, "heuristic"))

    # ── Crunchbase funding signals ───────────────────────────────────────────
    if enrichment:
        try:
            from app.services.enrichment.crunchbase import get_funding_signals
            domain = (lead.email.split("@")[-1]) if "@" in (lead.email or "") else None
            funding = get_funding_signals(lead.company or "", domain)
            if funding.get("recent_funding"):
                signals.append(("recent_funding", _RULE_MAP["recent_funding"].weight, funding["source"]))
            if funding.get("headcount_growth_6m", 0) > 0.10:
                signals.append(("headcount_growth", _RULE_MAP["headcount_growth"].weight, funding["source"]))
        except Exception:
            pass  # Crunchbase signals are optional

    # ── Persist signals & compute total ──────────────────────────────────────
    total = 0.0
    for signal_type, score, source in signals:
        total += score
        rule = _RULE_MAP.get(signal_type)
        db.add(IntentSignal(
            lead_id=lead.id,
            signal_type=signal_type,
            score=score,
            source=source,
            signal_metadata={"description": rule.description if rule else ""},
            captured_at=datetime.utcnow(),
        ))

    db.commit()
    final = round(min(1.0, total), 4)
    log.info(f"[intent] Lead {lead.id}: {len(signals)} signals → score={final}")
    return final


def get_lead_intent_score(db: Session, lead_id: str) -> float:
    """Return the sum of persisted intent signal scores for a lead (re-read from DB)."""
    signals = db.query(IntentSignal).filter(IntentSignal.lead_id == lead_id).all()
    return round(min(1.0, sum(s.score for s in signals)), 4)
