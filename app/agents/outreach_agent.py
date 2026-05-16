"""
Outreach Agent

Generates and sends personalised email sequences to qualified leads.

PoC: uses Python's smtplib with Gmail SMTP (free, 500 emails/day).
     Templates are stored in the DB; each step is personalised by the LLM.

# PRODUCTION email infrastructure options:
#   - SendGrid:  https://sendgrid.com/docs/api-reference/  (~$15/mo for 50k emails)
#                Use sendgrid-python SDK. Provides tracking webhooks (opens, clicks).
#   - Mailgun:   https://documentation.mailgun.com/          (free 1k/month, then $15+)
#   - Resend:    https://resend.com/docs/api-reference/emails/send-email (modern, simple)
#   - Lemlist:   https://developer.lemlist.com/              (built for cold outreach, $$)
#   - Instantly: https://app.instantly.ai/app/integrations   (high-volume cold email, $$)
#
# Tracking (open / click):
#   Embed a 1px tracking pixel (GET /track/open/{email_id}) and wrap links
#   (/track/click/{email_id}?url=...) to capture engagement events.
#   PRODUCTION: use SendGrid's built-in click/open tracking or a service like Litmus.
"""

import json
import logging
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.database import crud
from app.database.models import Lead, Enrichment, Verdict, OutreachEmail, OutreachSequence
from app.services.providers import get_ai_client
from app.config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default 3-step sequence (seeded on startup if no sequences exist)
# ---------------------------------------------------------------------------

DEFAULT_SEQUENCE_A = {
    "name": "Standard 3-Step (Variant A)",
    "ab_variant": "A",
    "steps": [
        {
            "step": 1,
            "delay_days": 0,
            "subject_template": "Quick question about {company}",
            "body_template": (
                "Hi {first_name},\n\n"
                "I came across {company} and noticed you're in the {industry} space. "
                "We help {industry} teams {value_prop}.\n\n"
                "Would it make sense to connect for a quick 15-minute call?\n\n"
                "Best,\n{sender_name}"
            ),
        },
        {
            "step": 2,
            "delay_days": 3,
            "subject_template": "Re: Quick question about {company}",
            "body_template": (
                "Hi {first_name},\n\n"
                "Wanted to follow up on my previous email. "
                "I know things get busy — is this something worth exploring?\n\n"
                "Happy to send over a 2-minute overview if that's easier.\n\n"
                "Best,\n{sender_name}"
            ),
        },
        {
            "step": 3,
            "delay_days": 7,
            "subject_template": "Closing the loop — {company}",
            "body_template": (
                "Hi {first_name},\n\n"
                "I'll keep this short — I don't want to be a pest. "
                "If now isn't the right time, no worries at all. "
                "Feel free to reach back out whenever the timing is better.\n\n"
                "Best,\n{sender_name}"
            ),
        },
    ],
}

DEFAULT_SEQUENCE_B = {
    "name": "Value-led 3-Step (Variant B)",
    "ab_variant": "B",
    "steps": [
        {
            "step": 1,
            "delay_days": 0,
            "subject_template": "How {industry} teams use us",
            "body_template": (
                "Hi {first_name},\n\n"
                "We recently helped a {company_size} company in {industry} {value_prop}. "
                "Thought it might be relevant for {company}.\n\n"
                "Worth a quick chat?\n\n"
                "Best,\n{sender_name}"
            ),
        },
        {
            "step": 2,
            "delay_days": 4,
            "subject_template": "A resource for {company}",
            "body_template": (
                "Hi {first_name},\n\n"
                "Following up — I put together a short case study that might be relevant. "
                "Happy to share it if you'd like.\n\n"
                "Let me know,\n{sender_name}"
            ),
        },
        {
            "step": 3,
            "delay_days": 8,
            "subject_template": "Last note — {company}",
            "body_template": (
                "Hi {first_name},\n\n"
                "Last email from me. If the timing is off, totally understand. "
                "I'll leave the door open.\n\n"
                "Best,\n{sender_name}"
            ),
        },
    ],
}


# ---------------------------------------------------------------------------
# LLM personalisation prompt
# ---------------------------------------------------------------------------

_PERSONALISE_PROMPT = """You are an expert B2B sales copywriter. Personalise the following email template for a specific lead.

Lead profile:
{profile_json}

Email template:
Subject: {subject_template}
Body:
{body_template}

Instructions:
- Replace all {{placeholders}} with real values from the lead profile
- Make the subject line and opening line specific to the lead (mention their company, role, or industry)
- Keep it under 120 words for the body
- Do NOT add fake metrics or claims you can't verify
- Sound human, not robotic

Respond with ONLY valid JSON:
{{
  "subject": "personalised subject line here",
  "body": "personalised email body here"
}}"""


class OutreachAgent(BaseAgent):
    """
    Selects the right A/B sequence variant, personalises each step with the LLM,
    schedules the emails in the DB, and sends step 1 immediately via SMTP.
    """

    name = "outreach"

    def __init__(self):
        self._ai = get_ai_client()

    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        lead = crud.get_lead(db, lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        # Skip if a verdict exists and it's Cold
        verdict = db.query(Verdict).filter(Verdict.lead_id == lead_id).first()
        if verdict and verdict.final_verdict == "Cold":
            log.info(f"[outreach] Lead {lead_id} is Cold — skipping outreach")
            return {"status": "skipped", "reason": "cold_lead"}

        enrichment = db.query(Enrichment).filter(Enrichment.lead_id == lead_id).first()

        # Pick A/B sequence variant
        sequence = self._pick_sequence(db)
        if sequence is None:
            sequence = self._seed_default_sequences(db)

        # Check if this lead already has outreach emails (idempotent)
        existing = db.query(OutreachEmail).filter(OutreachEmail.lead_id == lead_id).first()
        if existing:
            log.info(f"[outreach] Lead {lead_id} already has outreach scheduled — skipping")
            return {"status": "already_scheduled", "lead_id": lead_id}

        # Personalise and schedule all steps
        scheduled_emails = []
        for step in sequence.steps:
            subject, body = self._personalise(lead, enrichment, step)
            delay_days = step.get("delay_days", 0)
            scheduled_at = datetime.utcnow() + timedelta(days=delay_days)

            email_record = OutreachEmail(
                lead_id=lead_id,
                sequence_id=sequence.id,
                step_number=step["step"],
                subject=subject,
                body=body,
                status="scheduled",
                scheduled_at=scheduled_at,
            )
            db.add(email_record)
            scheduled_emails.append(email_record)

        db.commit()
        for e in scheduled_emails:
            db.refresh(e)

        # Send step 1 immediately if SMTP is configured
        step1 = next((e for e in scheduled_emails if e.step_number == 1), None)
        send_result = "smtp_not_configured"
        if step1 and settings.SMTP_HOST:
            send_result = self._send_email(db, step1, lead.email)

        log.info(f"[outreach] Lead {lead_id}: {len(scheduled_emails)} steps scheduled, step1={send_result}")
        return {
            "status": "scheduled",
            "sequence": sequence.name,
            "variant": sequence.ab_variant,
            "steps_scheduled": len(scheduled_emails),
            "step1_send": send_result,
        }

    # ── Sequence selection ──────────────────────────────────────────────────

    def _pick_sequence(self, db: Session) -> OutreachSequence | None:
        """Pick the A/B variant with fewest leads sent (even distribution)."""
        from app.database.models import ABTestResult
        sequences = db.query(OutreachSequence).filter(OutreachSequence.is_active).all()
        if not sequences:
            return None

        # Count emails sent per sequence
        counts: dict[str, int] = {}
        for seq in sequences:
            result = db.query(ABTestResult).filter(ABTestResult.sequence_id == seq.id).first()
            counts[seq.id] = result.emails_sent if result else 0

        # Return sequence with fewest sends so variants stay balanced
        return min(sequences, key=lambda s: counts.get(s.id, 0))

    def _seed_default_sequences(self, db: Session) -> OutreachSequence:
        """Create both default A/B sequences on first run."""
        for data in (DEFAULT_SEQUENCE_A, DEFAULT_SEQUENCE_B):
            seq = OutreachSequence(
                name=data["name"],
                ab_variant=data["ab_variant"],
                steps=data["steps"],
                is_active=True,
            )
            db.add(seq)
        db.commit()
        return db.query(OutreachSequence).filter(OutreachSequence.ab_variant == "A").first()

    # ── Personalisation ─────────────────────────────────────────────────────

    def _personalise(
        self,
        lead: Lead,
        enrichment: Enrichment | None,
        step: dict,
    ) -> tuple[str, str]:
        """Use LLM to personalise subject + body for the lead. Falls back to template substitution."""
        profile = {
            "name": lead.name,
            "first_name": lead.name.split()[0] if lead.name else "there",
            "email": lead.email,
            "company": lead.company,
            "industry": enrichment.industry if enrichment else "your industry",
            "job_title": enrichment.job_title if enrichment else "",
            "seniority": enrichment.seniority if enrichment else "",
            "company_size": enrichment.company_size if enrichment else "",
            "value_prop": "streamline their go-to-market motions with AI",
            "sender_name": settings.OUTREACH_SENDER_NAME,
        }

        prompt = _PERSONALISE_PROMPT.format(
            profile_json=json.dumps(profile, indent=2),
            subject_template=step["subject_template"],
            body_template=step["body_template"],
        )

        try:
            raw = self._ai.generate(prompt)
            parsed = self._parse_json(raw)
            return parsed["subject"], parsed["body"]
        except Exception as e:
            log.warning(f"[outreach] LLM personalisation failed ({e}), using template fallback")
            # Simple template substitution fallback
            subject = step["subject_template"].format(**profile)
            body = step["body_template"].format(**profile)
            return subject, body

    # ── SMTP delivery ───────────────────────────────────────────────────────

    def _send_email(self, db: Session, email_record: OutreachEmail, to_address: str) -> str:
        """
        Send via SMTP (Gmail / any SMTP relay).

        PoC: plain SMTP_SSL with username/password auth.

        # PRODUCTION SendGrid SDK replacement:
        #   import sendgrid
        #   from sendgrid.helpers.mail import Mail
        #   sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
        #   message = Mail(
        #       from_email=settings.OUTREACH_FROM_EMAIL,
        #       to_emails=to_address,
        #       subject=email_record.subject,
        #       plain_text_content=email_record.body,
        #   )
        #   resp = sg.send(message)
        #   # Attach tracking pixel: embed <img src="/track/open/{email_record.id}"> in HTML body
        #   return "sent" if resp.status_code == 202 else "failed"

        # PRODUCTION Mailgun:
        #   import requests
        #   resp = requests.post(
        #       f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
        #       auth=("api", settings.MAILGUN_API_KEY),
        #       data={"from": settings.OUTREACH_FROM_EMAIL, "to": to_address,
        #             "subject": email_record.subject, "text": email_record.body},
        #   )
        #   return "sent" if resp.ok else "failed"
        """
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = email_record.subject
            msg["From"] = settings.OUTREACH_FROM_EMAIL
            msg["To"] = to_address
            msg.attach(MIMEText(email_record.body, "plain"))

            # HTML part with open-tracking pixel embedded
            # The pixel fires a GET /track/open/{email_id} which records the open
            # PRODUCTION: also wrap every link with /track/click/{id}?url=... for click tracking
            if settings.APP_BASE_URL:
                pixel_url = f"{settings.APP_BASE_URL}/track/open/{email_record.id}"
                html_body = (
                    f"<html><body><pre style='font-family:sans-serif'>{email_record.body}</pre>"
                    f"<img src='{pixel_url}' width='1' height='1' style='display:none' /></body></html>"
                )
                msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.OUTREACH_FROM_EMAIL, [to_address], msg.as_string())

            email_record.status = "sent"
            email_record.sent_at = datetime.utcnow()
            db.commit()
            return "sent"

        except Exception as e:
            log.error(f"[outreach] SMTP send failed for {email_record.id}: {e}")
            email_record.status = "failed"
            email_record.error_message = str(e)
            db.commit()
            return f"failed: {e}"
