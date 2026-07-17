"""
The sourcing pipeline — originate leads without poisoning the database.

Gate order is deliberate and load-bearing:

  1. suppression   — never source someone who opted out (compliance first,
                     and before spending anything on them)
  2. dedup         — an existing lead is not a prospect
  3. verification  — undeliverable addresses never enter the DB; bounces are
                     what burn sending domains (skipped when the org has
                     verification disabled)
  4. scoring       — deterministic BANT (the same scorer backtests use), so
                     "why did the agent import this lead" always has an
                     answer; below-threshold candidates are rejected

Budget guardrails (max accepted/day) are enforced in code before any insert.
Dry runs execute every gate but write nothing — preview-before-import.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Enrichment, Lead, ProspectingRun
from app.services.backtest import qualify_row
from app.services.compliance import is_suppressed
from app.services.deduplication import DeduplicationService
from app.services.icp_service import get_icp_config
from app.services.prospecting.base import ProspectCandidate, ProspectSource
from app.utils.time import utcnow

log = logging.getLogger(__name__)


def get_prospect_source(name: str | None = None) -> ProspectSource:
    name = name or settings.PROSPECTING_PROVIDER
    if name == "pdl":
        from app.services.prospecting.pdl import PDLProspectSource
        return PDLProspectSource()
    from app.services.prospecting.synthetic import SyntheticProspectSource
    return SyntheticProspectSource()


def accepted_today(db: Session, org_id: str | None) -> int:
    """Accepted (non-dry-run) sourced leads in the current UTC day, org-scoped."""
    from sqlalchemy import func
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    q = db.query(func.coalesce(func.sum(ProspectingRun.accepted), 0)).filter(
        ProspectingRun.created_at >= day_start,
        ProspectingRun.dry_run == False,  # noqa: E712
    )
    if org_id is not None:
        q = q.filter(ProspectingRun.org_id == org_id)
    return int(q.scalar() or 0)


def _evaluate_candidate(db: Session, candidate: ProspectCandidate, org_id, icp_config, dedup) -> dict:
    """Run one candidate through the gates. Returns {verdict, score, gate}."""
    if is_suppressed(db, candidate.email, org_id=org_id):
        return {"gate": "suppressed"}

    if dedup.find_duplicates_by_email(candidate.email):
        return {"gate": "duplicate"}

    verification_status = "unknown"
    if settings.EMAIL_VERIFICATION_ENABLED:
        from app.services.email_verification import verify_email
        verification_status = verify_email(candidate.email).status
        if verification_status == "undeliverable":
            return {"gate": "undeliverable"}

    result = qualify_row(
        {
            "name": candidate.name,
            "email": candidate.email,
            "company": candidate.company,
            "job_title": candidate.job_title,
            "seniority": candidate.seniority,
            "industry": candidate.industry,
            "company_size": candidate.company_size,
        },
        icp_config,
    )
    if result["score"] < settings.PROSPECTING_MIN_SCORE:
        return {"gate": "low_score", "score": result["score"], "verdict": result["verdict"]}

    return {
        "gate": None,
        "score": result["score"],
        "verdict": result["verdict"],
        "icp_match": result["icp_match"],
        "verification_status": verification_status,
    }


def run_prospecting(
    db: Session,
    criteria: dict,
    limit: int,
    org_id: str | None = None,
    campaign_id: str | None = None,
    created_by_id: str | None = None,
    dry_run: bool = False,
    provider: str | None = None,
) -> ProspectingRun:
    """
    Source, gate, rank, and (unless dry_run) import up to `limit` leads.
    The returned run carries `preview` (transient attribute) with the gated
    candidates so callers can show exactly what happened per candidate.
    """
    source = get_prospect_source(provider)
    icp_config = get_icp_config(db, org_id=org_id)
    dedup = DeduplicationService(db)

    # Budget guardrail — before any provider spend beyond this batch
    budget_left = settings.PROSPECTING_MAX_LEADS_PER_DAY - accepted_today(db, org_id)
    effective_limit = limit if dry_run else max(0, min(limit, budget_left))

    # Over-fetch so gate rejections don't starve the accept count
    candidates = source.search(criteria or {}, limit * 2) if effective_limit > 0 or dry_run else []

    rejected = {"suppressed": 0, "duplicate": 0, "undeliverable": 0, "low_score": 0, "budget": 0}
    evaluated: list[tuple[ProspectCandidate, dict]] = []
    seen_emails: set[str] = set()

    for candidate in candidates:
        email = candidate.email.lower()
        if email in seen_emails:
            continue
        seen_emails.add(email)
        verdict = _evaluate_candidate(db, candidate, org_id, icp_config, dedup)
        if verdict["gate"]:
            rejected[verdict["gate"]] += 1
        else:
            evaluated.append((candidate, verdict))

    # Rank survivors by score, keep the best `limit` within budget
    evaluated.sort(key=lambda pair: pair[1]["score"], reverse=True)
    keep = evaluated[:effective_limit] if not dry_run else evaluated[:limit]
    # Over-limit survivors: count against budget when the daily budget (not
    # the requested limit) was the binding constraint; otherwise they simply
    # didn't make the top-N cut and aren't "rejected" in any meaningful sense
    overflow = len(evaluated) - len(keep)
    if overflow > 0 and not dry_run and effective_limit < limit:
        rejected["budget"] += overflow

    imported_ids = []
    if not dry_run:
        from app.services.timezone_service import infer_timezone
        for candidate, verdict in keep:
            lead = Lead(
                name=candidate.name,
                email=candidate.email.lower(),
                company=candidate.company,
                source=candidate.source,
                org_id=org_id,
                status="pending",
                timezone=infer_timezone(candidate.email),
            )
            db.add(lead)
            db.flush()
            # Seed enrichment from the provider's own data — the pipeline's
            # enrichment stage still runs and can improve on it
            db.add(Enrichment(
                lead_id=lead.id,
                job_title=candidate.job_title or None,
                seniority=candidate.seniority or None,
                industry=candidate.industry or None,
                company_size=candidate.company_size or None,
                confidence=0.6,
                enrichment_source=candidate.source,
            ))
            imported_ids.append(lead.id)

        db.commit()

        # Push into the qualification pipeline; Redis-less installs fall back
        # to the auto-enqueue scheduler picking up "pending" leads
        for lead_id in imported_ids:
            try:
                from app.services.queue_service import push_lead_job
                push_lead_job(lead_id)
            except Exception as e:
                log.debug(f"[prospecting] queue push deferred for {lead_id[:8]}: {e}")
                break

    total_cost = sum(
        (c.cost_usd or 0.0) for c, _ in keep
    ) if not dry_run else None

    run = ProspectingRun(
        org_id=org_id,
        campaign_id=campaign_id,
        provider=source.name,
        criteria=criteria or {},
        requested=limit,
        found=len(candidates),
        accepted=len(imported_ids) if not dry_run else 0,
        rejected=rejected,
        cost_usd=round(total_cost, 4) if total_cost is not None else None,
        dry_run=dry_run,
        created_by_id=created_by_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Transient preview for API responses (not persisted)
    run.preview = [
        {
            "name": c.name, "email": c.email, "company": c.company,
            "job_title": c.job_title, "industry": c.industry,
            "company_size": c.company_size,
            "score": v["score"], "verdict": v["verdict"],
            "icp_match": v.get("icp_match"),
            "verification_status": v.get("verification_status", "unknown"),
        }
        for c, v in keep
    ]

    log.info(
        f"[prospecting] {source.name}: requested={limit} found={len(candidates)} "
        f"accepted={run.accepted} rejected={rejected} dry_run={dry_run}"
    )
    return run
