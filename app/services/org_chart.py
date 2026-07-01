"""
Org Chart Traversal

When a lead is identified as wrong-level (IC, junior, or non-decision-maker),
this service finds the right decision-maker at the same company and creates a
linked lead for them.

Trigger conditions (checked after the validate node):
  - final_verdict flags contain "authority_too_low" or "too_junior"
  - BANT authority score < 0.45 (cannot buy unilaterally)
  - Lead seniority is Junior, IC, or Mid-Level

Detection method:
  Search for senior contacts at the same company using web search:
    "{company} VP OR Director OR Head of {function} site:linkedin.com"

  Parse result snippets for patterns like:
    "John Smith — VP of Sales at Acme Corp"
    "Jane Doe, Director of Revenue Operations"

  Extract name + title for each match. Filter out:
    - The current lead (same name)
    - Results that look like job listings (not people)
    - Titles below Manager level

For each found decision-maker:
  - Create a new Lead with source="org_chart"
  - Set referred_by_lead_id → the original lead's id
  - Queue the new lead for the pipeline
  - Add an event to the original lead's event log

This creates a referral chain: IC lead → VP found via org chart → pipeline.
The chain is visible via GET /leads/{id}/referred-leads.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from sqlalchemy.orm import Session

from app.config import settings

log = logging.getLogger(__name__)

_MIN_AUTHORITY_TO_SKIP = 0.45
_LOW_SENIORITY_LABELS = {"Junior", "IC", "Mid-Level", "Senior"}  # below director-level

# Titles that are clearly senior enough to be worth targeting
_TARGET_TITLE_KEYWORDS = [
    "vp", "vice president", "director", "head of", "chief", "cto", "ceo",
    "cro", "cpo", "vp of", "svp", "evp", "general manager", "president",
]

# Maximum new leads to create per org-chart traversal
_MAX_NEW_LEADS = 2


def _should_traverse(verdict, enrichment) -> bool:
    """Return True if org-chart traversal should be attempted for this lead."""
    if not verdict:
        return False

    # Check explicit flags from the debate/validate nodes
    flags = verdict.flags or []
    if isinstance(flags, list) and any(
        f in flags for f in ("authority_too_low", "too_junior", "authority_and_need_both_low")
    ):
        return True

    # Check BANT authority score
    bant = verdict.bant_scores or {}
    if float(bant.get("authority", 0.5)) < _MIN_AUTHORITY_TO_SKIP:
        # Only traverse if we have enrichment data to infer the function
        if enrichment and enrichment.seniority in _LOW_SENIORITY_LABELS:
            return True

    return False


def _infer_function(enrichment) -> str:
    """Infer the buyer's function from job title / industry for targeted search."""
    if not enrichment:
        return "Sales"
    title = (enrichment.job_title or "").lower()
    industry = (enrichment.industry or "").lower()

    if any(k in title for k in ("engineer", "developer", "sre", "devops", "architect")):
        return "Engineering"
    if any(k in title for k in ("product", "pm", "program manager")):
        return "Product"
    if any(k in title for k in ("marketing", "demand", "growth")):
        return "Marketing"
    if any(k in title for k in ("finance", "accounting", "cfo")):
        return "Finance"
    if any(k in industry for k in ("fintech", "banking", "insurance")):
        return "Revenue"
    return "Sales"


def _parse_decision_makers(results: list[dict], exclude_name: str) -> list[dict]:
    """
    Parse web search results to extract names and titles of senior contacts.
    Returns list of {name, title} dicts.
    """
    found = []
    seen_names = {exclude_name.lower() if exclude_name else ""}

    for result in results:
        text = result.get("title", "") + " " + result.get("snippet", "")

        # Pattern: "Name — Title at Company" or "Name, Title"
        name_title_patterns = [
            r"([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)[,\s\-–]+([A-Z][^,\n]+?(?:VP|Director|Head|Chief|President|CTO|CEO|CRO|CPO|SVP|EVP)[^,\n]*)",
            r"([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)[,\s]+(?:is|as|the)\s+([A-Z][^,\n]+?(?:VP|Director|Head|Chief|President|CTO|CEO|CRO|CPO)[^,\n]*)",
        ]
        for pattern in name_title_patterns:
            for m in re.finditer(pattern, text):
                name = m.group(1).strip()
                title = m.group(2).strip()
                if name.lower() in seen_names:
                    continue
                title_lower = title.lower()
                if any(kw in title_lower for kw in _TARGET_TITLE_KEYWORDS):
                    seen_names.add(name.lower())
                    found.append({"name": name, "title": title})
                    if len(found) >= _MAX_NEW_LEADS * 2:
                        return found

    return found[:_MAX_NEW_LEADS]


def traverse_org_chart(db: Session, lead_id: str) -> dict:
    """
    Attempt to find and create decision-maker leads for a low-authority lead.

    Returns:
      {
        traversed: bool,
        leads_created: int,
        decision_makers: [{name, title, lead_id}],
        reason_skipped: str | None,
      }
    """
    from app.database.models import Lead, Verdict, Enrichment
    from app.database import crud
    from app.services.queue_service import push_lead_job, LOW_PRIORITY
    from app.agents.research_agent import _search_web

    lead = crud.get_lead(db, lead_id)
    if not lead:
        return {"traversed": False, "reason_skipped": "lead_not_found"}

    verdict = db.query(Verdict).filter(Verdict.lead_id == lead_id).first()
    enrichment = db.query(Enrichment).filter(Enrichment.lead_id == lead_id).first()

    if not _should_traverse(verdict, enrichment):
        return {"traversed": False, "reason_skipped": "authority_sufficient"}

    company = lead.company or ""
    if not company:
        return {"traversed": False, "reason_skipped": "no_company"}

    function = _infer_function(enrichment)
    query = (
        f'"{company}" (VP OR Director OR "Head of" OR Chief) '
        f'"{function}" site:linkedin.com'
    )

    log.info(f"[org_chart] Traversing '{company}' for {function} leaders (lead {lead_id[:8]})")

    try:
        results = _search_web(query).get("results", [])
    except Exception as e:
        log.warning(f"[org_chart] Search failed for {company}: {e}")
        return {"traversed": False, "reason_skipped": f"search_error: {e}"}

    if not results:
        return {"traversed": False, "reason_skipped": "no_search_results"}

    decision_makers = _parse_decision_makers(results, exclude_name=lead.name or "")
    if not decision_makers:
        return {"traversed": False, "reason_skipped": "no_decision_makers_found"}

    created = []
    for dm in decision_makers[:_MAX_NEW_LEADS]:
        # Build a synthetic email — deterministic so duplicates are caught
        name_slug = re.sub(r"[^a-z0-9]", ".", dm["name"].lower())
        company_slug = re.sub(r"[^a-z0-9]", "", company.lower())
        synthetic_email = f"{name_slug}@{company_slug}.com"

        from app.database.models import Lead as LeadModel
        existing = db.query(LeadModel).filter(LeadModel.email == synthetic_email).first()
        if existing:
            log.debug(f"[org_chart] {dm['name']} already in DB — skipping")
            continue

        new_lead = crud.create_lead(
            db,
            name=dm["name"],
            email=synthetic_email,
            company=company,
            source="org_chart",
        )
        new_lead.referred_by_lead_id = lead_id
        new_lead.quality_metadata = {
            "title_from_org_chart": dm["title"],
            "discovered_via": "web_search",
            "original_lead_id": lead_id,
            "function": function,
        }
        db.commit()

        try:
            push_lead_job(new_lead.id, priority=LOW_PRIORITY)
        except Exception:
            pass

        try:
            crud.append_lead_event(db, lead_id, "org_chart.decision_maker_found", payload={
                "dm_name": dm["name"],
                "dm_title": dm["title"],
                "new_lead_id": new_lead.id,
            }, agent_name="org_chart")
        except Exception:
            pass

        created.append({"name": dm["name"], "title": dm["title"], "lead_id": new_lead.id})
        log.info(
            f"[org_chart] Created DM lead: '{dm['name']}' ({dm['title']}) "
            f"at {company} — referred from {lead_id[:8]}"
        )

    return {
        "traversed": True,
        "leads_created": len(created),
        "decision_makers": created,
        "reason_skipped": None,
    }
