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

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from typing import Any

from app.database.connection import get_db
from app.database import crud
from app.services.queue_service import push_lead_job
from app.config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _normalise_email(email: str) -> str:
    return email.strip().lower()


def _create_and_queue(db: Session, name: str, email: str, company: str, source: str) -> dict:
    """Deduplicate → create lead → push queue job. Returns result dict."""
    email = _normalise_email(email)

    # PoC dedup: check by email only
    # PRODUCTION: use probabilistic matching on (email, name, domain, phone) via Clearbit's /v2/people/find
    from app.database.models import Lead
    existing = db.query(Lead).filter(Lead.email == email).first()
    if existing:
        log.info(f"[ingest] Duplicate detected for {email} (existing={existing.id})")
        return {"status": "duplicate", "lead_id": existing.id, "email": email}

    lead = crud.create_lead(db, name=name, email=email, company=company, source=source)
    push_lead_job(lead.id)
    log.info(f"[ingest/{source}] New lead queued: {lead.id} ({email})")
    return {"status": "queued", "lead_id": lead.id, "email": email}


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
):
    """Accept a website form submission and queue it for qualification."""
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
):
    """Accept a lead from a marketing ad platform and queue it for qualification."""
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
):
    """Accept a parsed inbound email and queue it for qualification."""
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
):
    """Accept a LinkedIn signal (profile visit / DM) and queue it for qualification."""
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
):
    """Accept an event/webinar registration and queue it for qualification."""
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
