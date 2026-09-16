"""
Email open/click tracking pixels and redirects.

Extracted from app/main.py, which had grown to ~3.5k lines and 87 endpoints.
Route order matters in FastAPI — concrete paths must be registered before the
`/{lead_id}` style catch-alls — and that is far easier to keep right in a
file scoped to one concern.
"""

import json  # noqa: F401
import re  # noqa: F401
import asyncio  # noqa: F401
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks  # noqa: F401
from fastapi.responses import Response, RedirectResponse, StreamingResponse  # noqa: F401
from sqlalchemy.orm import Session  # noqa: F401
import structlog

from app.database.connection import get_db  # noqa: F401
from app.database import crud  # noqa: F401
from app.database.models import Lead, Enrichment, Verdict, User  # noqa: F401
from app.auth.dependencies import require_admin, require_manager, require_rep  # noqa: F401
from app.config import settings  # noqa: F401
from app.utils.time import utcnow  # noqa: F401
from app.services.queue_service import push_lead_job, get_redis  # noqa: F401

log = structlog.get_logger(__name__)

router = APIRouter(tags=["tracking"])

# 1x1 transparent GIF returned by the open-tracking endpoint.
_TRACKING_PIXEL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!"
    b"\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


@router.get("/track/open/{email_id}", include_in_schema=False)
def track_open(email_id: str, db: Session = Depends(get_db)):
    """
    Called when a lead opens an email (via embedded <img> tag).
    Records the open time and returns a transparent 1×1 GIF so the
    email client doesn't display a broken image.

    Embed in outreach HTML body:
      <img src="{BASE_URL}/track/open/{email_id}" width="1" height="1" />
    """
    from app.database.models import OutreachEmail
    from app.services.ab_testing import record_event
    try:
        email = db.query(OutreachEmail).filter(OutreachEmail.id == email_id).first()
        if email and not email.opened_at:
            email.opened_at = utcnow()
            email.status = "opened"
            db.commit()
            record_event(db, email_id, "opened")
            log.info(f"[track/open] Email {email_id} opened")
            # Bayesian BANT update + autonomous re-qualification check
            if email.lead_id:
                from app.services.bayesian_updater import apply_bayesian_update
                from app.database.models import Verdict as _Verdict
                result = apply_bayesian_update(db, email.lead_id, "open")
                if result:
                    # If a Cold/Warm lead now crosses the Hot confidence threshold,
                    # push them back into the full qualification pipeline.
                    new_conf = result["new_confidence"]
                    verdict_row = (
                        db.query(_Verdict)
                        .filter(_Verdict.lead_id == email.lead_id)
                        .first()
                    )
                    current_verdict = verdict_row.final_verdict if verdict_row else None
                    requeued = False
                    if new_conf >= 0.70 and current_verdict in ("Cold", "Warm", None):
                        try:
                            push_lead_job(email.lead_id)
                            crud.update_lead_status(db, email.lead_id, "pending")
                            log.info(
                                f"[track/open] Re-queued lead {email.lead_id[:8]} for re-qualification "
                                f"(confidence {new_conf:.2f} crossed threshold, was {current_verdict})"
                            )
                            requeued = True
                        except Exception as _rq_err:
                            log.warning(f"[track/open] Re-queue failed: {_rq_err}")
                    try:
                        import redis as _redis
                        import json as _json
                        _r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
                        _r.publish("asdr:global_events", _json.dumps({
                            "type": "score_update",
                            "lead_id": email.lead_id,
                            "signal": "open",
                            "new_confidence": new_conf,
                            "requeued": requeued,
                        }))
                        _r.close()
                    except Exception:
                        pass
    except Exception as e:
        log.warning("[track/open] Failed to record open for {email_id}", error=str(e))
    return Response(content=_TRACKING_PIXEL, media_type="image/gif")

@router.get("/track/click/{email_id}", include_in_schema=False)
def track_click(
    email_id: str,
    url: str = Query(..., description="Destination URL after click is recorded"),
    db: Session = Depends(get_db),
):
    """
    Called when a lead clicks a tracked link.
    Records the click, then redirects to the real destination URL.

    Wrap links in outreach body:
      href="{BASE_URL}/track/click/{email_id}?url={urllib.parse.quote(real_url)}"
    """
    from app.database.models import OutreachEmail
    from app.services.ab_testing import record_event
    try:
        email = db.query(OutreachEmail).filter(OutreachEmail.id == email_id).first()
        if email:
            if not email.opened_at:
                email.opened_at = utcnow()
                email.status = "opened"
                record_event(db, email_id, "opened")
            db.commit()
            log.info(f"[track/click] Email {email_id} clicked → {url[:80]}")
            # Clicks are a stronger intent signal than opens — apply Bayesian update
            # and re-qualify at a lower threshold (0.60) since clicking shows real interest.
            if email.lead_id:
                from app.services.bayesian_updater import apply_bayesian_update
                from app.database.models import Verdict as _VerdictC
                result = apply_bayesian_update(db, email.lead_id, "click")
                if result and result["new_confidence"] >= 0.60:
                    verdict_row = (
                        db.query(_VerdictC)
                        .filter(_VerdictC.lead_id == email.lead_id)
                        .first()
                    )
                    if verdict_row and verdict_row.final_verdict in ("Cold", "Warm", None):
                        try:
                            push_lead_job(email.lead_id)
                            crud.update_lead_status(db, email.lead_id, "pending")
                            log.info(
                                f"[track/click] Re-queued lead {email.lead_id[:8]} after click "
                                f"(confidence={result['new_confidence']:.2f})"
                            )
                        except Exception:
                            pass
    except Exception as e:
        log.warning("[track/click] Failed to record click for {email_id}", error=str(e))
    return RedirectResponse(url=url, status_code=302)

@router.get("/track/visit", include_in_schema=False)
def track_visit(
    request: Request,
    page: str = Query("unknown", description="Page slug, e.g. 'pricing', 'home'"),
    ref: str = Query("", description="Document referrer (optional)"),
    db: Session = Depends(get_db),
):
    """
    Website visitor de-anonymization pixel.

    Embed on any page to identify corporate visitors without a form submission:
      <img src="{BASE_URL}/track/visit?page=pricing" width="1" height="1"
           style="display:none" />

    When a company employee visits from a corporate IP, we identify their
    company via reverse-IP lookup and create a lead with source="ip_visit".
    Subsequent visits from the same identified company add a pricing_page_visit
    intent signal to the existing lead (capped to one per 3 days).

    Returns the same 1x1 transparent GIF as the email open pixel.
    """
    from datetime import timedelta
    from app.services.ip_intelligence import identify_visitor, is_private_ip
    from app.database.models import IntentSignal

    # Resolve real visitor IP through common proxy headers
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = (
        forwarded.split(",")[0].strip()
        or request.headers.get("X-Real-IP", "")
        or (request.client.host if request.client else "")
    )

    if ip and not is_private_ip(ip):
        try:
            identity = identify_visitor(ip)
            if identity["identified"] and identity["company"]:
                company = identity["company"]
                domain = identity.get("domain") or ""
                # Synthetic email built from company name — deterministic so dupes are caught
                synthetic_email = f"visitor@{domain}" if domain else (
                    f"visitor+{re.sub(r'[^a-z0-9]', '', company.lower())}@unknown.com"
                )

                existing = db.query(Lead).filter(Lead.email == synthetic_email).first()
                if not existing:
                    new_lead = crud.create_lead(
                        db,
                        name=f"{company} (Anonymous Visitor)",
                        email=synthetic_email,
                        company=company,
                        source="ip_visit",
                    )
                    new_lead.identified_via_ip = True
                    new_lead.quality_metadata = {
                        "ip_org": identity.get("org_raw"),
                        "city": identity.get("city"),
                        "country": identity.get("country"),
                        "visited_page": page,
                        "referrer": ref[:200] if ref else "",
                    }
                    db.commit()
                    try:
                        from app.services.queue_service import push_lead_job
                        push_lead_job(new_lead.id)
                    except Exception:
                        pass
                    log.info(
                        f"[track/visit] New IP lead: '{company}' "
                        f"from {ip[:8]}*** page={page}"
                    )
                else:
                    # Add / refresh a pricing_page_visit intent signal
                    cutoff = utcnow() - timedelta(days=3)
                    recent = (
                        db.query(IntentSignal)
                        .filter(
                            IntentSignal.lead_id == existing.id,
                            IntentSignal.signal_type == "pricing_page_visit",
                            IntentSignal.captured_at > cutoff,
                        )
                        .first()
                    )
                    if not recent:
                        db.add(IntentSignal(
                            lead_id=existing.id,
                            signal_type="pricing_page_visit",
                            score=0.25,
                            source="ip_intelligence",
                            signal_metadata={
                                "page": page,
                                "city": identity.get("city"),
                                "country_code": identity.get("country_code"),
                            },
                        ))
                        db.commit()
                        log.info(
                            f"[track/visit] Visit signal added for '{existing.name}' "
                            f"page={page}"
                        )
        except Exception as e:
            log.debug(f"[track/visit] identification failed for {ip}: {e}")

    return Response(content=_TRACKING_PIXEL, media_type="image/gif")
