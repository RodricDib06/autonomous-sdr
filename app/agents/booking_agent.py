"""
Booking Agent

Sends qualified leads a meeting booking link and tracks booking status.

PoC: uses Cal.com's free self-hosted API (or cal.com cloud free tier).
     If no Cal.com API key is set, generates a mock booking link so the
     rest of the pipeline (CRM sync, Slack notification) still works.

Cal.com free tier:
  - Unlimited event types and bookings on cal.com cloud
  - Self-hostable under AGPL — https://github.com/calcom/cal.com
  - REST API docs: https://cal.com/docs/api-reference/v2/introduction

# PRODUCTION Calendly (paid alternative):
#   Calendly does not allow booking on behalf of a user via API alone.
#   The practical approach is to store the user's scheduling link and send it.
#   To create single-use links (avoid double-booking), use:
#     POST https://api.calendly.com/scheduling_links
#     Headers: Authorization: Bearer {CALENDLY_TOKEN}
#     Body: {"max_event_count": 1, "owner": "https://api.calendly.com/event_types/{uuid}", "owner_type": "EventType"}
#   Docs: https://developer.calendly.com/api-docs
#
# PRODUCTION HubSpot Meetings:
#   HubSpot provides a hosted meeting scheduler with CRM integration.
#   Embed link: https://meetings.hubspot.com/{username}
#   No API to create single-use links on the free tier.
"""

import logging
import uuid as uuid_lib
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.database.models import Lead, Verdict, BookingRequest
from app.database import crud
from app.services.slack_notifier import SlackNotifier
from app.config import settings

log = logging.getLogger(__name__)


class BookingAgent(BaseAgent):
    """
    Creates a booking request record, sends the lead a scheduling link,
    and posts a Slack alert so the assigned rep is ready.
    """

    name = "booking"

    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        lead = crud.get_lead(db, lead_id)
        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        verdict = db.query(Verdict).filter(Verdict.lead_id == lead_id).first()
        if verdict and verdict.final_verdict == "Cold":
            log.info(f"[booking] Lead {lead_id} is Cold — skipping booking")
            return {"status": "skipped", "reason": "cold_lead"}

        # Idempotency — don't double-book
        existing = (
            db.query(BookingRequest)
            .filter(
                BookingRequest.lead_id == lead_id,
                BookingRequest.status.in_(["pending", "link_sent", "confirmed"]),
            )
            .first()
        )
        if existing:
            log.info(f"[booking] Lead {lead_id} already has a booking request ({existing.id})")
            return {"status": "already_exists", "booking_id": existing.id}

        # Generate / fetch booking link
        booking_link, external_id = self._get_booking_link(lead)

        booking = BookingRequest(
            lead_id=lead_id,
            status="link_sent",
            booking_link=booking_link,
            external_booking_id=external_id,
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)

        # Notify Slack
        self._notify_slack(lead, verdict, booking_link)

        # Generate pre-call brief asynchronously (best-effort, never blocks booking)
        self._generate_brief_async(db, lead_id)

        log.info(f"[booking] Lead {lead_id}: booking link sent → {booking_link}")
        return {
            "status": "link_sent",
            "booking_id": booking.id,
            "booking_link": booking_link,
            "external_id": external_id,
        }

    # ── Booking link generation ─────────────────────────────────────────────

    def _get_booking_link(self, lead: Lead) -> tuple[str, str | None]:
        """
        Returns (booking_link, external_id).

        If CAL_API_KEY is configured, creates a single-use booking link via Cal.com API.
        Otherwise returns the generic scheduling page URL.

        # PRODUCTION Cal.com single-use link creation:
        #   import requests
        #   resp = requests.post(
        #       "https://api.cal.com/v2/bookings",
        #       headers={
        #           "Authorization": f"Bearer {settings.CAL_API_KEY}",
        #           "cal-api-version": "2024-08-13",
        #           "Content-Type": "application/json",
        #       },
        #       json={
        #           "eventTypeId": settings.CAL_EVENT_TYPE_ID,
        #           "attendee": {
        #               "name": lead.name,
        #               "email": lead.email,
        #               "timeZone": "UTC",
        #           },
        #           "metadata": {"lead_id": lead.id},
        #       },
        #   )
        #   data = resp.json()["data"]
        #   return data["meetingUrl"], str(data["id"])
        #
        # PRODUCTION Calendly single-use link:
        #   import requests
        #   resp = requests.post(
        #       "https://api.calendly.com/scheduling_links",
        #       headers={"Authorization": f"Bearer {settings.CALENDLY_TOKEN}"},
        #       json={
        #           "max_event_count": 1,
        #           "owner": f"https://api.calendly.com/event_types/{settings.CALENDLY_EVENT_TYPE_UUID}",
        #           "owner_type": "EventType",
        #       },
        #   )
        #   url = resp.json()["resource"]["booking_url"]
        #   return url, None
        """
        if settings.CAL_API_KEY and settings.CAL_SCHEDULING_URL:
            # Real Cal.com: just return the static scheduling link for PoC
            # (single-use link creation shown in comment above)
            link = settings.CAL_SCHEDULING_URL
            external_id = None
        elif settings.CAL_SCHEDULING_URL:
            link = settings.CAL_SCHEDULING_URL
            external_id = None
        else:
            # Fully mocked — still functional for demos
            mock_id = str(uuid_lib.uuid4())[:8]
            link = f"https://cal.com/demo/{mock_id}"
            external_id = f"mock_{mock_id}"
            log.info(f"[booking] No Cal.com URL configured — using mock link: {link}")

        return link, external_id

    # ── Pre-call brief ──────────────────────────────────────────────────────

    def _generate_brief_async(self, db: Session, lead_id: str) -> None:
        """Generate a pre-call brief in a background thread so booking is instant."""
        import threading
        from app.database.connection import SessionLocal

        def _run():
            brief_db = SessionLocal()
            try:
                from app.agents.pre_call_brief_agent import PreCallBriefAgent
                PreCallBriefAgent()._timed_run(brief_db, lead_id, {})
            except Exception as e:
                log.warning(f"[booking] Pre-call brief generation failed for {lead_id[:8]}: {e}")
            finally:
                brief_db.close()

        threading.Thread(target=_run, daemon=True).start()

    # ── Slack notification ──────────────────────────────────────────────────

    def _notify_slack(self, lead: Lead, verdict: Verdict | None, booking_link: str) -> None:
        """Post a Slack alert so the assigned rep can prep for the call."""
        notifier = SlackNotifier(settings.SLACK_WEBHOOK_URL)
        if not notifier.enabled:
            return

        verdict_label = verdict.final_verdict if verdict else "Unscored"
        confidence = f"{verdict.confidence_score:.0%}" if verdict and verdict.confidence_score else "N/A"

        message = (
            f":calendar: *Booking link sent* to {lead.name} ({lead.company})\n"
            f"Verdict: *{verdict_label}* | Confidence: {confidence}\n"
            f"Link: {booking_link}"
        )
        try:
            notifier.notify(message)
        except Exception as e:
            log.warning(f"[booking] Slack notification failed: {e}")
