"""
Job Change Detector

Monitors enriched leads for role changes — detecting when a contact has moved
to a new company or taken a new title. Job changes are the #1 trigger for
outbound success: the new hire has budget, is building their stack, and hasn't
yet chosen incumbents.

Detection strategy (two-tier):

  Tier 1 — PDL re-enrichment (accurate, uses API calls):
    Re-query People Data Labs for leads originally enriched via PDL.
    If job_company_name differs from lead.company, a change is confirmed.
    Requires PDL_API_KEY. Limited to 100 free calls/month so we only check
    leads that haven't been re-checked in 7+ days.

  Tier 2 — Web search signal (free, lower confidence):
    For leads without PDL, search "{name} joined {new company}" or
    "{name} new role" to surface LinkedIn announcements. Marks confidence
    as "low" so downstream agents can treat the lead accordingly.

When a change is detected:
  1. An IntentSignal of type "job_change_trigger" (score 0.30) is created
  2. An OutreachEmail is created with a personalized "just saw your move" template
  3. lead.last_trigger_checked_at is updated
  4. The lead's company field is updated to the new company (PDL tier only)

Cooldown: 60 days — we won't re-fire a job_change_trigger for the same lead
within this window, since the person needs time to settle in.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.utils.time import utcnow

log = logging.getLogger(__name__)

_JOB_CHANGE_COOLDOWN_DAYS = 60
_RECHECK_INTERVAL_DAYS = 7
_MAX_LEADS_PER_RUN = 30  # PDL budget guard

# Email template for job change outreach
_SUBJECT = "Congrats on the new role at {new_company}"
_BODY = (
    "Hi {first_name},\n\n"
    "I noticed you recently joined {new_company} — congrats on the move! "
    "Starting a new role is one of the best times to think about which tools "
    "and systems to bring in or upgrade.\n\n"
    "We've helped a number of {function} leaders at companies like {new_company} "
    "hit the ground running. Worth a quick 15-minute conversation?\n\n"
    "Best,\n{sender_name}"
)


# ---------------------------------------------------------------------------
# PDL-based detection
# ---------------------------------------------------------------------------

def _check_pdl_job_change(lead, enrichment) -> dict | None:
    """
    Re-query PDL and compare current company to stored enrichment company.
    Returns change details dict or None.
    """
    if not settings.PDL_API_KEY:
        return None
    if not (lead.email and enrichment and enrichment.enrichment_source == "pdl"):
        return None

    try:
        import requests as _req
        resp = _req.get(
            "https://api.peopledatalabs.com/v5/person/enrich",
            params={"api_key": settings.PDL_API_KEY, "email": lead.email, "pretty": False},
            timeout=8,
        )
        if resp.status_code in (402, 404):
            return None
        resp.raise_for_status()
        data = resp.json()
        if data.get("likelihood", 0) < 0.5:
            return None

        current_company = (data.get("job_company_name") or "").strip()
        stored_company = (lead.company or "").strip()

        if not current_company or current_company.lower() == stored_company.lower():
            return None

        new_title = data.get("job_title") or enrichment.job_title or "their new role"
        return {
            "previous_company": stored_company,
            "new_company": current_company,
            "new_title": new_title,
            "confidence": "high",
            "source": "pdl",
        }
    except Exception as e:
        log.debug(f"[job_change] PDL re-check failed for {lead.email}: {e}")
        return None


# ---------------------------------------------------------------------------
# Web search fallback detection
# ---------------------------------------------------------------------------

def _check_web_job_change(lead) -> dict | None:
    """
    Search for LinkedIn-style job change announcements via web search.
    Returns change details dict or None.
    """
    if not lead.name or not lead.company:
        return None
    try:
        from app.agents.research_agent import _search_web
        query = f'"{lead.name}" "new role" OR "joined" OR "excited to announce" 2026'
        result = _search_web(query)
        snippets = result.get("results", [])

        company_lower = (lead.company or "").lower()
        for r in snippets:
            text = (r.get("title", "") + " " + r.get("snippet", "")).lower()
            # Must mention the person's name and a joining phrase but NOT their old company
            if lead.name.split()[0].lower() in text:
                if any(kw in text for kw in ("joined", "new role", "excited to join", "starting at")):
                    if company_lower not in text:
                        # Try to extract new company from snippet
                        new_company = _extract_company_from_snippet(r.get("snippet", ""), lead.name)
                        if new_company and new_company.lower() != company_lower:
                            return {
                                "previous_company": lead.company,
                                "new_company": new_company,
                                "new_title": None,
                                "confidence": "low",
                                "source": "web_search",
                                "snippet": r.get("snippet", "")[:150],
                            }
        return None
    except Exception as e:
        log.debug(f"[job_change] web search failed for {lead.name}: {e}")
        return None


def _extract_company_from_snippet(snippet: str, name: str) -> str | None:
    """
    Heuristic: look for patterns like "joined Acme" or "at Acme" in text.
    Returns the company name fragment or None.
    """
    import re
    patterns = [
        r"joined\s+([A-Z][A-Za-z0-9\s&,\.]+?)[\s,\.\!]",
        r"at\s+([A-Z][A-Za-z0-9\s&]+?)[\s,\.\!]",
        r"starting at\s+([A-Z][A-Za-z0-9\s&]+?)[\s,\.\!]",
    ]
    for pattern in patterns:
        m = re.search(pattern, snippet)
        if m:
            candidate = m.group(1).strip()
            # Filter out names and very short/long matches
            if 3 < len(candidate) < 40 and name.split()[0] not in candidate:
                return candidate
    return None


# ---------------------------------------------------------------------------
# Cooldown check
# ---------------------------------------------------------------------------

def _is_on_cooldown(db: Session, lead_id: str) -> bool:
    from app.database.models import IntentSignal
    cutoff = utcnow() - timedelta(days=_JOB_CHANGE_COOLDOWN_DAYS)
    existing = (
        db.query(IntentSignal)
        .filter(
            IntentSignal.lead_id == lead_id,
            IntentSignal.signal_type == "job_change_trigger",
            IntentSignal.captured_at > cutoff,
        )
        .first()
    )
    return existing is not None


# ---------------------------------------------------------------------------
# Outreach email builder
# ---------------------------------------------------------------------------

def _build_job_change_email(lead, change: dict) -> tuple[str, str]:
    first_name = lead.name.split()[0] if lead.name else "there"
    new_company = change.get("new_company", "your new company")
    new_title = change.get("new_title", "")

    function = "revenue"
    if new_title:
        t = new_title.lower()
        if any(k in t for k in ("sales", "sdr", "bdr", "account")):
            function = "sales"
        elif any(k in t for k in ("marketing", "demand", "growth")):
            function = "marketing"
        elif any(k in t for k in ("engineer", "developer", "cto")):
            function = "engineering"
        elif any(k in t for k in ("product", "pm", "cpo")):
            function = "product"

    subject = _SUBJECT.format(new_company=new_company)
    body = _BODY.format(
        first_name=first_name,
        new_company=new_company,
        function=function,
        sender_name=settings.OUTREACH_SENDER_NAME,
    )
    return subject, body


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_job_change_check(db: Session) -> dict:
    """
    Check eligible leads for job changes. Called by the scheduler every 48 hours.

    Eligibility: status=complete, not on cooldown, last_trigger_checked_at >
    RECHECK_INTERVAL_DAYS ago (shared field with trigger_monitor).
    """
    from app.database.models import Lead, Verdict, OutreachEmail, IntentSignal
    from sqlalchemy.orm import selectinload

    recheck_cutoff = utcnow() - timedelta(days=_RECHECK_INTERVAL_DAYS)

    candidates = (
        db.query(Lead)
        .join(Verdict, Lead.id == Verdict.lead_id)
        .filter(
            Lead.status == "complete",
            Lead.archived == False,  # noqa: E712
            Verdict.final_verdict.in_(["Warm", "Hot", "Cold"]),  # check all — job change reactivates Cold
            (Lead.last_trigger_checked_at == None) | (Lead.last_trigger_checked_at < recheck_cutoff),  # noqa: E711
        )
        .options(selectinload(Lead.enrichments))
        .limit(_MAX_LEADS_PER_RUN)
        .all()
    )

    checked = 0
    changed = 0
    errors = 0

    for lead in candidates:
        try:
            if _is_on_cooldown(db, lead.id):
                lead.last_trigger_checked_at = utcnow()
                checked += 1
                continue

            enrichment = lead.enrichments[0] if lead.enrichments else None

            # Try PDL first, then web search
            change = _check_pdl_job_change(lead, enrichment) or _check_web_job_change(lead)

            if change:
                new_company = change["new_company"]
                log.info(
                    f"[job_change] '{lead.name}' moved from '{lead.company}' "
                    f"→ '{new_company}' (confidence={change['confidence']})"
                )

                # Persist intent signal
                db.add(IntentSignal(
                    lead_id=lead.id,
                    signal_type="job_change_trigger",
                    score=0.30,
                    source=change["source"],
                    signal_metadata=change,
                ))

                # Build and schedule outreach email
                subject, body = _build_job_change_email(lead, change)
                db.add(OutreachEmail(
                    lead_id=lead.id,
                    sequence_id=None,
                    step_number=1,
                    subject=subject,
                    body=body,
                    status="scheduled",
                    scheduled_at=utcnow(),
                    quality_flags=["job_change_trigger", f"confidence:{change['confidence']}"],
                    quality_reasoning=f"Job change: {lead.company} → {new_company}",
                ))

                # Update lead company if high-confidence PDL data
                if change["confidence"] == "high":
                    lead.company = new_company
                    if enrichment and change.get("new_title"):
                        enrichment.job_title = change["new_title"]

                changed += 1

            lead.last_trigger_checked_at = utcnow()
            checked += 1

        except Exception as e:
            errors += 1
            log.warning(f"[job_change] error processing lead {lead.id[:8]}: {e}")

    try:
        db.commit()
    except Exception as e:
        log.error(f"[job_change] commit failed: {e}")
        db.rollback()

    summary = {"checked": checked, "changed": changed, "errors": errors}
    if checked:
        log.info(f"[job_change] job complete: {summary}")
    return summary
