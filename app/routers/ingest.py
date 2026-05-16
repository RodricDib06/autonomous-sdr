"""
Lead Ingestion Router — /ingest/*

Five webhook endpoints, one per ingestion channel:
  POST /ingest/form          — website form submissions (HubSpot, Webflow, Typeform, etc.)
  POST /ingest/ads           — marketing ad platform lead forms (Meta, Google, LinkedIn Ads)
  POST /ingest/email         — inbound email parsed by a mail relay (Postmark, SendGrid Inbound)
  POST /ingest/linkedin      — LinkedIn profile visits / DM signals (via Phantombuster or webhook)
  POST /ingest/event         — webinar / demo registration (Zoom, Eventbrite, etc.)

PoC approach: each endpoint accepts a generic JSON payload, normalises it to the
internal LeadCreate schema, deduplicates, then pushes to the processing queue.

# PRODUCTION integrations (commented per endpoint below):
#   - Meta Lead Ads:   https://developers.facebook.com/docs/marketing-api/guides/lead-ads/retrieval
#   - Google Lead Ads: https://developers.google.com/google-ads/api/docs/leads/overview
#   - LinkedIn Ads:    https://learn.microsoft.com/en-us/linkedin/marketing/integrations/lead-gen/lead-gen-integration
#   - HubSpot Forms:   https://developers.hubspot.com/docs/api/marketing/forms
#   - Webflow Forms:   https://developers.webflow.com/reference/create-form-submission
#   - Postmark:        https://postmarkapp.com/developer/webhooks/inbound-webhook
#   - SendGrid Inbound: https://docs.sendgrid.com/for-developers/parsing-email/inbound-email
#   - Phantombuster:   https://phantombuster.com/api — LinkedIn scraper with webhook push
#   - Zoom Webinars:   https://developers.zoom.us/docs/api/rest/reference/zoom-api/methods/#operation/webinarRegistrants
#   - Eventbrite:      https://www.eventbrite.com/platform/api#/reference/webhook
"""

import hashlib
import hmac
import logging
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from typing import Any

import structlog

from app.database.connection import get_db
from app.database import crud
from app.services.queue_service import push_lead_job
from app.services.rate_limiter import limiter
from app.config import settings

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])

# ---------------------------------------------------------------------------
# Webhook secret verification
# ---------------------------------------------------------------------------

def _verify_webhook_secret(secret: str | None) -> None:
    """
    Validate the X-Webhook-Secret header against WEBHOOK_SECRET env var.
    Skipped when WEBHOOK_SECRET is not configured (dev / open demo mode).

    PRODUCTION: always set WEBHOOK_SECRET and verify on every ingest endpoint.
    Use HMAC-SHA256 for platform-specific signatures (Meta, HubSpot, etc.):
      computed = hmac.new(secret_bytes, raw_body, sha256).hexdigest()
      if not hmac.compare_digest(computed, header_value): raise 403
    """
    configured = settings.WEBHOOK_SECRET
    if not configured:
        return   # no secret configured → open mode (dev / demo)
    if not secret:
        raise HTTPException(status_code=403, detail="Missing X-Webhook-Secret header")
    if not hmac.compare_digest(configured, secret):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _normalise_email(email: str) -> str:
    return email.strip().lower()


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _create_and_queue(db: Session, name: str, email: str, company: str, source: str) -> dict:
    """Deduplicate → validate → create lead → push queue job → track status in Redis."""
    email = _normalise_email(email)

    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail=f"Invalid email address: {email}")

    # PoC dedup: check by email only
    # PRODUCTION: probabilistic matching on (email, name, domain, phone) via Clearbit /v2/people/find
    from app.database.models import Lead
    existing = db.query(Lead).filter(Lead.email == email).first()
    if existing:
        log.info("ingest.duplicate", email=email, existing_id=existing.id[:8])
        return {"status": "duplicate", "lead_id": existing.id, "email": email}

    lead = crud.create_lead(db, name=name, email=email, company=company, source=source)
    push_lead_job(lead.id)

    # Track job status in Redis (TTL 24 h) so callers can poll GET /jobs/{lead_id}
    try:
        from app.services.queue_service import get_redis
        import json as _json
        get_redis().setex(
            f"job:{lead.id}",
            86_400,
            _json.dumps({"lead_id": lead.id, "status": "queued", "source": source}),
        )
    except Exception:
        pass

    log.info("ingest.queued", source=source, lead_id=lead.id[:8], email=email)
    return {"status": "queued", "job_id": lead.id, "lead_id": lead.id, "email": email}


# ---------------------------------------------------------------------------
# 1. Website form submissions
# ---------------------------------------------------------------------------

class FormPayload(BaseModel):
    """
    Generic form payload — covers HubSpot, Webflow, Typeform, and any custom form.

    # PRODUCTION HubSpot Forms webhook:
    #   The webhook sends a list of form field objects. Map them like:
    #     name  = fields["firstname"] + " " + fields["lastname"]
    #     email = fields["email"]
    #     company = fields["company"]
    #   Verify via HMAC: X-HubSpot-Signature header + your app secret.
    #   Docs: https://developers.hubspot.com/docs/api/marketing/forms#webhook

    # PRODUCTION Webflow Forms webhook:
    #   Body is {"data": {"Name": ..., "Email": ..., ...}, "name": "form-name", ...}
    #   Docs: https://developers.webflow.com/reference/create-form-submission
    """
    name: str
    email: str
    company: str
    message: str | None = None
    # Pass-through: any extra fields from the form (UTM params, page URL, etc.)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/form")
def ingest_form(
    payload: FormPayload,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(None),
):
    """Accept a website form submission and queue it for qualification."""
    _verify_webhook_secret(x_webhook_secret)
    try:
        result = _create_and_queue(
            db,
            name=payload.name,
            email=payload.email,
            company=payload.company,
            source="website_form",
        )
        return result
    except Exception as e:
        log.error(f"[ingest/form] Failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to ingest form submission")


# ---------------------------------------------------------------------------
# 2. Marketing ad lead forms
# ---------------------------------------------------------------------------

class AdsPayload(BaseModel):
    """
    Normalised payload for ad platform lead forms.

    # PRODUCTION Meta Lead Ads:
    #   1. Subscribe to leadgen webhook in Meta Business Suite.
    #   2. Verify webhook with hub.verify_token before going live.
    #   3. On each POST, retrieve the lead using the Graph API:
    #        GET /v18.0/{leadgen_id}?access_token={page_access_token}
    #   4. Map field_data array: {"name":"email","values":["foo@bar.com"]}
    #   Docs: https://developers.facebook.com/docs/marketing-api/guides/lead-ads/retrieval

    # PRODUCTION Google Lead Form Extensions:
    #   Configure a webhook URL in Google Ads → Assets → Lead forms.
    #   Payload: {"google_key": ..., "user_column_data": [{"column_name":"email","string_value":...}]}
    #   Docs: https://developers.google.com/google-ads/api/docs/leads/overview

    # PRODUCTION LinkedIn Lead Gen Forms:
    #   Use the LinkedIn Marketing Solutions streaming API or a third-party connector.
    #   Docs: https://learn.microsoft.com/en-us/linkedin/marketing/integrations/lead-gen
    """
    platform: str = "unknown"   # "meta" | "google" | "linkedin_ads"
    name: str
    email: str
    company: str | None = None
    phone: str | None = None
    ad_id: str | None = None
    campaign_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/ads")
def ingest_ads(
    payload: AdsPayload,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(None),
):
    """Accept a lead from a marketing ad platform and queue it for qualification."""
    _verify_webhook_secret(x_webhook_secret)
    try:
        company = payload.company or f"via {payload.platform} ad"
        result = _create_and_queue(
            db,
            name=payload.name,
            email=payload.email,
            company=company,
            source="marketing_ad",
        )
        return {**result, "platform": payload.platform, "ad_id": payload.ad_id}
    except Exception as e:
        log.error(f"[ingest/ads] Failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to ingest ad lead")


# ---------------------------------------------------------------------------
# 3. Inbound email
# ---------------------------------------------------------------------------

class EmailPayload(BaseModel):
    """
    Pre-parsed inbound email from a mail relay.

    # PRODUCTION Postmark Inbound Webhook:
    #   Configure the inbound address in Postmark → Servers → Inbound.
    #   Fields: From, FromName, Subject, TextBody, HtmlBody, etc.
    #   Extract name/email from `From` header; parse company from email domain.
    #   Docs: https://postmarkapp.com/developer/webhooks/inbound-webhook

    # PRODUCTION SendGrid Inbound Parse:
    #   Configure MX records to point to SendGrid.
    #   Fields: from (RFC 5322), subject, text, html.
    #   Docs: https://docs.sendgrid.com/for-developers/parsing-email/inbound-email

    # PRODUCTION Gmail API (push notifications):
    #   Use Gmail API + Cloud Pub/Sub to receive new message notifications.
    #   Then fetch the message, parse headers, and extract sender info.
    #   Docs: https://developers.google.com/gmail/api/guides/push
    """
    from_name: str
    from_email: str
    subject: str | None = None
    body_text: str | None = None
    # Company inferred from email domain when not explicitly provided
    company: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/email")
def ingest_email(
    payload: EmailPayload,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(None),
):
    """Accept a parsed inbound email and queue it for qualification."""
    _verify_webhook_secret(x_webhook_secret)
    try:
        # Infer company from email domain when not given
        company = payload.company
        if not company:
            domain = payload.from_email.split("@")[-1] if "@" in payload.from_email else ""
            company = domain.split(".")[0].title() if domain else "Unknown"

        result = _create_and_queue(
            db,
            name=payload.from_name,
            email=payload.from_email,
            company=company,
            source="inbound_email",
        )
        return result
    except Exception as e:
        log.error(f"[ingest/email] Failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to ingest email lead")


# ---------------------------------------------------------------------------
# 4. LinkedIn signals
# ---------------------------------------------------------------------------

class LinkedInPayload(BaseModel):
    """
    LinkedIn profile visit or DM — delivered by a scraping tool or webhook relay.

    # PRODUCTION LinkedIn Partner API:
    #   LinkedIn's official API only exposes lead data to Certified Marketing Partners.
    #   For most companies the practical options are:
    #     a) LinkedIn Lead Gen Forms (covered under /ingest/ads)
    #     b) Sales Navigator API (enterprise tier, $$$)
    #        Docs: https://learn.microsoft.com/en-us/linkedin/sales/overview
    #     c) Third-party tools: Phantombuster, Expandi, Waalaxy — they export CSVs
    #        or post to a webhook after scraping profile visits / connection requests.

    # PoC: any tool that can POST name + email + company works here.
    """
    name: str
    email: str | None = None
    linkedin_url: str | None = None
    company: str | None = None
    signal_type: str = "profile_visit"   # "profile_visit" | "connection_request" | "dm"
    message_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/linkedin")
def ingest_linkedin(
    payload: LinkedInPayload,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(None),
):
    """Accept a LinkedIn signal (profile visit / DM) and queue it for qualification."""
    _verify_webhook_secret(x_webhook_secret)
    try:
        if not payload.email:
            # Without an email we can't deduplicate or enrich — log and skip.
            # PRODUCTION: use Clearbit Reveal or Apollo to resolve email from LinkedIn URL.
            log.warning(f"[ingest/linkedin] No email for {payload.name} — skipped")
            return {"status": "skipped", "reason": "no_email", "name": payload.name}

        company = payload.company or "Unknown (LinkedIn)"
        result = _create_and_queue(
            db,
            name=payload.name,
            email=payload.email,
            company=company,
            source="linkedin_signal",
        )
        return {**result, "signal_type": payload.signal_type}
    except Exception as e:
        log.error(f"[ingest/linkedin] Failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to ingest LinkedIn signal")


# ---------------------------------------------------------------------------
# 5. Event / webinar registrations
# ---------------------------------------------------------------------------

class EventPayload(BaseModel):
    """
    Webinar or demo registration from an event platform.

    # PRODUCTION Zoom Webinars:
    #   Configure a Zoom webhook subscription for webinar.registrant_created.
    #   Payload includes registrant: {first_name, last_name, email, org, ...}
    #   Docs: https://developers.zoom.us/docs/api/rest/reference/zoom-api/methods/#operation/webinarRegistrants

    # PRODUCTION Eventbrite:
    #   Subscribe to order.placed webhook in Eventbrite Webhooks dashboard.
    #   Fetch attendee details via GET /v3/events/{id}/attendees/
    #   Docs: https://www.eventbrite.com/platform/api#/reference/webhook

    # PRODUCTION Hopin / Goldcast / Bizzabo:
    #   Each has its own webhook format — normalise to this schema in a thin adapter.
    """
    event_name: str
    event_id: str | None = None
    attendee_name: str
    attendee_email: str
    attendee_company: str | None = None
    registered_at: str | None = None   # ISO 8601
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/event")
def ingest_event(
    payload: EventPayload,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(None),
):
    """Accept an event/webinar registration and queue it for qualification."""
    _verify_webhook_secret(x_webhook_secret)
    try:
        company = payload.attendee_company or f"via event: {payload.event_name}"
        result = _create_and_queue(
            db,
            name=payload.attendee_name,
            email=payload.attendee_email,
            company=company,
            source="event",
        )
        return {**result, "event": payload.event_name}
    except Exception as e:
        log.error(f"[ingest/event] Failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to ingest event registration")


# ---------------------------------------------------------------------------
# 6. Universal webhook — auto-detects format (Typeform, Zapier, Make, n8n)
# ---------------------------------------------------------------------------

@router.post("/webhook")
@limiter.limit("100/minute")
async def ingest_universal_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(None),
):
    """
    Universal ingest endpoint — accepts any JSON payload and heuristically
    extracts name / email / company.  Designed for Zapier, Make.com, n8n,
    Typeform, and any tool that can send a generic webhook.

    Field resolution order (first non-empty wins):
      email   → email | Email | from | from_email | lead_email
      name    → name | Name | full_name | first_name+last_name | fullName
      company → company | Company | organization | org | account

    Zapier example action:
      URL: https://your-app.railway.app/ingest/webhook
      Headers: X-Webhook-Secret: <your secret>
      Body: { "email": "{{email}}", "name": "{{name}}", "company": "{{company}}" }

    Typeform hidden fields:
      Add a hidden field for `company`; map Typeform fields to the keys above.

    # PRODUCTION: verify platform-specific HMAC signatures (Typeform uses
    # sha256=<hex> in the Typeform-Signature header; compute and compare before
    # calling _create_and_queue).
    """
    _verify_webhook_secret(x_webhook_secret)

    try:
        body: dict = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON")

    def _pick(*keys: str) -> str:
        for k in keys:
            v = body.get(k) or body.get(k.lower()) or body.get(k.title())
            if v and str(v).strip():
                return str(v).strip()
        return ""

    email = _pick("email", "Email", "from_email", "lead_email", "from")
    if not email:
        raise HTTPException(status_code=422, detail="Could not find an email field in the payload")

    first = _pick("first_name", "firstName", "firstname")
    last  = _pick("last_name",  "lastName",  "lastname")
    name  = _pick("name", "Name", "full_name", "fullName") or f"{first} {last}".strip() or email.split("@")[0]
    company = _pick("company", "Company", "organization", "org", "account", "firm")
    if not company:
        company = email.split("@")[-1].split(".")[0].title()

    # Auto-detect source from payload hints
    source = _pick("source", "channel", "form_name", "platform") or "website_form"
    known_sources = {"inbound_email", "linkedin_signal", "event", "marketing_ad", "website_form"}
    if source not in known_sources:
        source = "website_form"

    try:
        result = _create_and_queue(db, name=name, email=email, company=company, source=source)
        return {**result, "detected_source": source, "raw_keys": list(body.keys())}
    except HTTPException:
        raise
    except Exception as e:
        log.error("ingest.webhook.error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to process webhook payload")


# ---------------------------------------------------------------------------
# 7. Job status — poll pipeline progress after ingest
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}")
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """
    Poll the processing status of a lead submitted via any /ingest/* endpoint.

    Returns:
      { job_id, status: queued|processing|complete|failed|not_found, lead_id, verdict? }

    Typical polling loop (JS):
      const poll = async (id) => {
        const r = await fetch(`/ingest/jobs/${id}`);
        const j = await r.json();
        if (j.status === 'complete') return j.verdict;
        setTimeout(() => poll(id), 3000);
      };
    """
    import json as _json

    # Check Redis cache first (fast path)
    try:
        from app.services.queue_service import get_redis
        cached = get_redis().get(f"job:{job_id}")
        if cached:
            data = _json.loads(cached)
            # Augment with live DB status if available
            from app.database.models import Lead, Verdict
            lead = db.query(Lead).filter(Lead.id == job_id).first()
            if lead:
                verdict_row = db.query(Verdict).filter(Verdict.lead_id == job_id).first()
                return {
                    "job_id": job_id,
                    "lead_id": job_id,
                    "status": lead.status,
                    "verdict": verdict_row.final_verdict if verdict_row else None,
                    "source": data.get("source"),
                }
    except Exception:
        pass

    # Fallback: DB lookup
    from app.database.models import Lead, Verdict
    lead = db.query(Lead).filter(Lead.id == job_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Job not found")

    verdict_row = db.query(Verdict).filter(Verdict.lead_id == job_id).first()
    return {
        "job_id": job_id,
        "lead_id": job_id,
        "status": lead.status,
        "verdict": verdict_row.final_verdict if verdict_row else None,
    }
