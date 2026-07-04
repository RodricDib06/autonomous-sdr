"""
Real-Time Trigger Monitor

Watches for company-level events that signal buying intent and creates
personalized outreach emails when a trigger fires. Runs on a scheduled job
every 6 hours against Warm and Hot leads that haven't been checked recently.

Trigger types (in priority order):
  funding_trigger      — company raised a new round since last check
  job_posting_trigger  — company is actively hiring in a role we can help with
  news_trigger         — company appeared in relevant news (product launch, expansion)

For each trigger found:
  1. A new IntentSignal is persisted with the trigger payload in signal_metadata
  2. A context-personalized OutreachEmail is created (status=scheduled)
  3. lead.last_trigger_checked_at is updated so we don't re-check immediately

Cooldowns prevent spam:
  - Funding trigger: 30 days before re-triggering on same signal type
  - Job posting: 14 days
  - News: 7 days

Web search uses Tavily (1000 free searches/month) or DuckDuckGo as fallback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings

log = logging.getLogger(__name__)

# How many hours between trigger checks per lead
_CHECK_INTERVAL_HOURS = 6

# Cooldown per trigger type before we fire the same trigger again
_COOLDOWNS: dict[str, int] = {
    "funding_trigger": 30,
    "job_posting_trigger": 14,
    "news_trigger": 7,
}

# Roles that signal a company is scaling their GTM/revenue stack —
# seeing these in job postings means they need our product category
_GTM_ROLES = [
    "sales development representative", "sdr", "business development representative",
    "account executive", "revenue operations", "revops", "sales operations",
    "sales enablement", "demand generation", "growth hacker", "growth marketer",
    "vp of sales", "head of sales", "chief revenue officer", "cro",
]

# Keywords in news that indicate buying signals
_NEWS_BUYING_KEYWORDS = [
    "launched", "launch", "raised", "funding", "series", "expanded", "expansion",
    "acquired", "acquisition", "ipo", "partnership", "partnership announced",
    "record revenue", "hypergrowth", "scaling", "hiring",
]


# ---------------------------------------------------------------------------
# Web search helper — reuses research_agent infrastructure
# ---------------------------------------------------------------------------

def _search(query: str) -> list[dict]:
    """Search the web and return a list of {title, snippet} dicts."""
    try:
        from app.agents.research_agent import _search_web
        result = _search_web(query)
        return result.get("results", [])
    except Exception as e:
        log.debug(f"[trigger] search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Trigger detection
# ---------------------------------------------------------------------------

def _detect_funding_trigger(company: str, domain: str | None) -> dict | None:
    """Check Crunchbase for a funding round announced in the last 30 days."""
    try:
        from app.services.enrichment.crunchbase import get_funding_signals
        signals = get_funding_signals(company, domain)
        if not signals.get("recent_funding"):
            return None
        announced = signals.get("announced_on")
        if announced:
            try:
                days_ago = (datetime.utcnow().date() - datetime.fromisoformat(announced).date()).days
                if days_ago > 30:
                    return None
            except ValueError:
                pass
        amount = signals.get("funding_amount_usd")
        ftype = signals.get("funding_type") or "round"
        amount_str = f"${amount:,.0f}" if amount else ""
        return {
            "trigger_type": "funding_trigger",
            "headline": f"{company} raised {amount_str} {ftype}".strip(),
            "amount_usd": amount,
            "funding_type": ftype,
            "announced_on": signals.get("announced_on"),
            "source": signals.get("source", "crunchbase"),
        }
    except Exception as e:
        log.debug(f"[trigger] funding check failed for {company}: {e}")
        return None


def _detect_job_posting_trigger(company: str) -> dict | None:
    """Search for GTM/revenue role job postings at this company."""
    query = (
        f'"{company}" hiring ("sales development" OR "sdr" OR "revenue operations" '
        f'OR "account executive" OR "head of sales") 2026'
    )
    results = _search(query)
    if not results:
        return None

    combined = " ".join(r.get("title", "") + " " + r.get("snippet", "") for r in results).lower()
    found_roles = [role for role in _GTM_ROLES if role in combined]
    if not found_roles:
        return None

    role_label = found_roles[0].title()
    return {
        "trigger_type": "job_posting_trigger",
        "headline": f"{company} is hiring for {role_label}",
        "roles_detected": found_roles[:3],
        "search_snippets": [r.get("title") for r in results[:2]],
        "source": "web_search",
    }


def _detect_news_trigger(company: str) -> dict | None:
    """Search for company news with buying signal keywords."""
    query = f'"{company}" 2026 (launched OR raised OR expansion OR partnership OR announcement)'
    results = _search(query)
    if not results:
        return None

    for result in results:
        text = (result.get("title", "") + " " + result.get("snippet", "")).lower()
        matched = [kw for kw in _NEWS_BUYING_KEYWORDS if kw in text]
        if matched:
            return {
                "trigger_type": "news_trigger",
                "headline": result.get("title", f"{company} in the news"),
                "keywords_matched": matched[:3],
                "snippet": result.get("snippet", "")[:200],
                "source": "web_search",
            }
    return None


# ---------------------------------------------------------------------------
# Trigger outreach templates
# ---------------------------------------------------------------------------

_TRIGGER_SUBJECTS = {
    "funding_trigger": "Congrats on the {funding_type} — quick thought",
    "job_posting_trigger": "Noticed {company} is hiring for {role}",
    "news_trigger": "Saw {company} in the news",
}

_TRIGGER_BODIES = {
    "funding_trigger": (
        "Hi {first_name},\n\n"
        "Congrats on {company}'s {funding_type}! "
        "That kind of growth usually comes with a push to build out the go-to-market stack. "
        "We help teams at exactly this stage do exactly that — worth a quick chat?\n\n"
        "Best,\n{sender_name}"
    ),
    "job_posting_trigger": (
        "Hi {first_name},\n\n"
        "Noticed {company} is scaling its {function} team — always a sign of healthy momentum. "
        "We work with teams at your stage to accelerate those same motions, "
        "often cutting ramp time for new hires significantly.\n\n"
        "Happy to share how — interested?\n\n"
        "Best,\n{sender_name}"
    ),
    "news_trigger": (
        "Hi {first_name},\n\n"
        "Caught {company} in the news recently — impressive. "
        "Timing felt right to check in. "
        "We've been working with a few similar companies on [specific challenge]. "
        "Could be worth a quick conversation.\n\n"
        "Best,\n{sender_name}"
    ),
}


def _build_trigger_email(lead, enrichment, trigger: dict) -> tuple[str, str]:
    """Build subject + body for a trigger-based outreach email."""
    first_name = lead.name.split()[0] if lead.name else "there"
    company = lead.company or "your company"
    sender = settings.OUTREACH_SENDER_NAME
    ttype = trigger["trigger_type"]

    subject_tpl = _TRIGGER_SUBJECTS.get(ttype, "Following up on {company}")
    body_tpl = _TRIGGER_BODIES.get(ttype, "Hi {first_name},\n\nWanted to reach out.\n\nBest,\n{sender_name}")

    fmt = {
        "first_name": first_name,
        "company": company,
        "sender_name": sender,
        "funding_type": trigger.get("funding_type", "round"),
        "role": (trigger.get("roles_detected") or ["Sales"])[0].title(),
        "function": _infer_function(trigger.get("roles_detected", [])),
    }

    try:
        subject = subject_tpl.format(**fmt)
        body = body_tpl.format(**fmt)
    except KeyError:
        subject = f"Quick thought on {company}"
        body = f"Hi {first_name},\n\nWanted to reach out following some news about {company}.\n\nBest,\n{sender}"

    return subject, body


def _infer_function(roles: list[str]) -> str:
    if not roles:
        return "revenue"
    role = roles[0].lower()
    if "sdr" in role or "sales development" in role or "business development" in role:
        return "SDR/BDR"
    if "revenue" in role or "revops" in role or "operations" in role:
        return "revenue operations"
    if "account executive" in role or "ae" in role:
        return "account executive"
    if "marketing" in role or "demand" in role:
        return "marketing"
    return "sales"


# ---------------------------------------------------------------------------
# Cooldown check
# ---------------------------------------------------------------------------

def _is_on_cooldown(db: Session, lead_id: str, trigger_type: str) -> bool:
    """Return True if this trigger was already fired recently for this lead."""
    from app.database.models import IntentSignal
    cooldown_days = _COOLDOWNS.get(trigger_type, 14)
    cutoff = datetime.utcnow() - timedelta(days=cooldown_days)
    existing = (
        db.query(IntentSignal)
        .filter(
            IntentSignal.lead_id == lead_id,
            IntentSignal.signal_type == trigger_type,
            IntentSignal.captured_at > cutoff,
        )
        .first()
    )
    return existing is not None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_trigger_check_job(db: Session) -> dict:
    """
    Check all eligible leads for real-time triggers. Called by the scheduler
    every 6 hours.

    Eligibility: status=complete, last_trigger_checked_at is None or stale.
    Now includes Cold leads — a funding event is strong enough to resurrect
    a previously-disqualified lead by re-pushing it through the full pipeline.

    Returns a summary dict for logging.
    """
    from app.database.models import Lead, Verdict, OutreachEmail, IntentSignal
    from app.services.queue_service import push_lead_job
    from sqlalchemy.orm import selectinload

    cutoff = datetime.utcnow() - timedelta(hours=_CHECK_INTERVAL_HOURS)

    # Include ALL complete leads (not just Warm/Hot) so Cold leads can be resurrected.
    candidates = (
        db.query(Lead)
        .outerjoin(Verdict, Lead.id == Verdict.lead_id)
        .filter(
            Lead.status == "complete",
            Lead.archived == False,  # noqa: E712
            (Lead.last_trigger_checked_at == None) | (Lead.last_trigger_checked_at < cutoff),  # noqa: E711
        )
        .options(selectinload(Lead.enrichments))
        .limit(50)  # cap per run to stay within Tavily free tier
        .all()
    )

    triggered = 0
    resurrected = 0
    checked = 0
    errors = 0

    for lead in candidates:
        try:
            enrichment = lead.enrichments[0] if lead.enrichments else None
            domain = lead.email.split("@")[-1] if "@" in (lead.email or "") else None

            verdict_row = db.query(Verdict).filter(Verdict.lead_id == lead.id).first()
            current_verdict = verdict_row.final_verdict if verdict_row else None

            # Use a closure to capture the correct lead/domain values per iteration
            company = lead.company or ""
            detectors = [
                lambda c=company, d=domain: _detect_funding_trigger(c, d),
                lambda c=company: _detect_job_posting_trigger(c),
                lambda c=company: _detect_news_trigger(c),
            ]

            for detect in detectors:
                trigger = detect()
                if not trigger:
                    continue
                ttype = trigger["trigger_type"]
                if _is_on_cooldown(db, lead.id, ttype):
                    log.debug(f"[trigger] {ttype} on cooldown for {lead.id[:8]}")
                    continue

                # Persist intent signal
                weight = {"funding_trigger": 0.25, "job_posting_trigger": 0.15, "news_trigger": 0.10}
                db.add(IntentSignal(
                    lead_id=lead.id,
                    signal_type=ttype,
                    score=weight.get(ttype, 0.10),
                    source=trigger.get("source", "web_search"),
                    signal_metadata=trigger,
                ))

                # Cold lead resurrection: funding is a high-conviction reversal signal.
                # Re-push through the full pipeline instead of just sending an email.
                if current_verdict == "Cold" and ttype == "funding_trigger":
                    try:
                        from app.database import crud
                        crud.update_lead_status(db, lead.id, "pending")
                        db.commit()
                        push_lead_job(lead.id)
                        resurrected += 1
                        log.info(
                            f"[trigger] RESURRECTION: Cold lead '{lead.name}' @ {lead.company} "
                            f"re-queued after funding trigger: {trigger.get('headline', '')[:80]}"
                        )
                    except Exception as _rq_err:
                        log.warning(f"[trigger] resurrection re-queue failed: {_rq_err}")
                else:
                    # Warm/Hot leads and non-funding triggers: create trigger outreach email
                    subject, body = _build_trigger_email(lead, enrichment, trigger)
                    db.add(OutreachEmail(
                        lead_id=lead.id,
                        sequence_id=None,
                        step_number=1,
                        subject=subject,
                        body=body,
                        status="scheduled",
                        scheduled_at=datetime.utcnow(),
                        quality_flags=[ttype],
                        quality_reasoning=f"Trigger-based outreach: {trigger.get('headline', '')}",
                    ))

                triggered += 1
                log.info(
                    f"[trigger] {ttype} fired for '{lead.name}' @ {lead.company}: "
                    f"{trigger.get('headline', '')[:80]}"
                )
                break  # one trigger per lead per cycle

            lead.last_trigger_checked_at = datetime.utcnow()
            checked += 1

        except Exception as e:
            errors += 1
            log.warning(f"[trigger] error processing lead {lead.id[:8]}: {e}")

    try:
        db.commit()
    except Exception as e:
        log.error(f"[trigger] commit failed: {e}")
        db.rollback()

    summary = {"checked": checked, "triggered": triggered, "resurrected": resurrected, "errors": errors}
    if checked:
        log.info(f"[trigger] job complete: {summary}")
    return summary
