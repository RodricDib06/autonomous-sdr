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
from datetime import timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.agents.email_judge_agent import EmailJudgeAgent
from app.database import crud
from app.database.models import Lead, Enrichment, Verdict, OutreachEmail, OutreachSequence
from app.services.providers import get_ai_client
from app.config import settings
from app.utils.time import utcnow

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

_PERSONALISE_PROMPT_RETRY = """You are an expert B2B sales copywriter. Personalise the following email template for a specific lead.

Lead profile:
{profile_json}

Email template:
Subject: {subject_template}
Body:
{body_template}

A quality reviewer rejected your previous attempt with this specific feedback:
"{improvement_hint}"

Fix exactly that issue. Do not introduce new problems.

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
        self._judge = EmailJudgeAgent()

    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        lead = crud.get_lead(db, lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        # Never contact suppressed addresses (unsubscribed / bounced / DNC)
        from app.services.compliance import is_suppressed
        suppression = is_suppressed(db, lead.email, org_id=lead.org_id)
        if suppression:
            log.info(
                f"[outreach] Lead {lead_id} is on the suppression list "
                f"({suppression.value}, source={suppression.source}) — skipping outreach"
            )
            return {"status": "skipped", "reason": "suppressed", "suppression_source": suppression.source}

        # Skip if a verdict exists and it's Cold
        verdict = db.query(Verdict).filter(Verdict.lead_id == lead_id).first()
        if verdict and verdict.final_verdict == "Cold":
            log.info(f"[outreach] Lead {lead_id} is Cold — skipping outreach")
            return {"status": "skipped", "reason": "cold_lead"}

        enrichment = db.query(Enrichment).filter(Enrichment.lead_id == lead_id).first()

        # Pick A/B sequence variant (org's own sequences, falling back to global)
        sequence = self._pick_sequence(db, org_id=lead.org_id)
        if sequence is None:
            sequence = self._seed_default_sequences(db)

        # Check if this lead already has outreach emails (idempotent)
        existing = db.query(OutreachEmail).filter(OutreachEmail.lead_id == lead_id).first()
        if existing:
            log.info(f"[outreach] Lead {lead_id} already has outreach scheduled — skipping")
            return {"status": "already_scheduled", "lead_id": lead_id}

        # Autonomy dial: in "approve" and "draft" modes nothing sends until a
        # human signs off — emails land in the approval queue instead.
        from app.services.tenancy import get_org_setting
        autonomy_mode = get_org_setting(
            db, lead.org_id, "autonomy_mode", settings.DEFAULT_AUTONOMY_MODE
        )
        initial_status = "scheduled" if autonomy_mode == "auto" else "pending_approval"

        # Personalise and schedule all steps
        scheduled_emails = []
        for step in sequence.steps:
            subject, body, quality = self._personalise_with_judge(lead, enrichment, step)
            delay_days = step.get("delay_days", 0)
            scheduled_at = utcnow() + timedelta(days=delay_days)

            email_record = OutreachEmail(
                lead_id=lead_id,
                sequence_id=sequence.id,
                step_number=step["step"],
                subject=subject,
                body=body,
                status=initial_status,
                scheduled_at=scheduled_at,
                quality_score=quality.get("overall_score"),
                quality_flags=quality.get("issues") or [],
                quality_reasoning=quality.get("improvement_hint") or "",
            )
            db.add(email_record)
            scheduled_emails.append(email_record)

        db.commit()
        for e in scheduled_emails:
            db.refresh(e)

        # Send step 1 immediately — full-auto mode only
        step1 = next((e for e in scheduled_emails if e.step_number == 1), None)
        if autonomy_mode != "auto":
            send_result = f"held_for_approval ({autonomy_mode} mode)"
        elif step1 and settings.SMTP_HOST:
            send_result = self._send_email(db, step1, lead.email)
        else:
            send_result = "smtp_not_configured"

        log.info(f"[outreach] Lead {lead_id}: {len(scheduled_emails)} steps scheduled, step1={send_result}")
        return {
            "status": "scheduled" if autonomy_mode == "auto" else "pending_approval",
            "autonomy_mode": autonomy_mode,
            "sequence": sequence.name,
            "variant": sequence.ab_variant,
            "steps_scheduled": len(scheduled_emails),
            "step1_send": send_result,
        }

    # ── Sequence selection ──────────────────────────────────────────────────

    def _pick_sequence(self, db: Session, org_id: str | None = None) -> OutreachSequence | None:
        """Select an A/B variant using Thompson Sampling.

        Routes more traffic to the better-performing variant as conversion data
        accumulates, while never fully stopping exploration of other variants.
        Falls back to even-split when no sequences exist.
        """
        from app.database.models import ABTestResult
        from app.services.bandit import thompson_select

        seq_q = db.query(OutreachSequence).filter(OutreachSequence.is_active)
        if org_id is not None:
            org_sequences = seq_q.filter(OutreachSequence.org_id == org_id).all()
            # Fall back to global (org-less) sequences when the org has none
            sequences = org_sequences or seq_q.filter(OutreachSequence.org_id.is_(None)).all()
        else:
            sequences = seq_q.all()
        if not sequences:
            return None

        # Build variant state dicts for the bandit
        variant_states = []
        for seq in sequences:
            ab_result = db.query(ABTestResult).filter(ABTestResult.sequence_id == seq.id).first()
            variant_states.append({
                "id": seq.id,
                "ab_variant": seq.ab_variant,
                "emails_sent": ab_result.emails_sent if ab_result else 0,
                "conversions": ab_result.conversions if ab_result else 0,
            })

        chosen = thompson_select(variant_states)
        log.info(
            f"[outreach] bandit selected variant={chosen.get('ab_variant')} "
            f"θ={chosen.get('thompson_sample', 0):.3f}"
        )

        return next(s for s in sequences if s.id == chosen["id"])

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

    def _personalise_with_judge(
        self,
        lead: Lead,
        enrichment: Enrichment | None,
        step: dict,
    ) -> tuple[str, str, dict]:
        """Personalise an email and gate it through the quality judge.

        Returns (subject, body, quality_result). On rejection, regenerates once
        with the judge's improvement_hint. If the retry still fails the judge,
        we use the retry output anyway (better than the original) and log it.
        """
        profile = self._build_profile(lead, enrichment)
        subject, body = self._personalise(profile, step)

        quality = self._judge.score(subject=subject, body=body, profile=profile)
        if not quality["passed"] and quality.get("improvement_hint"):
            log.info(
                f"[outreach] email rejected by judge (score={quality['overall_score']:.1f}), "
                f"retrying with hint: {quality['improvement_hint']}"
            )
            subject, body = self._personalise(profile, step, improvement_hint=quality["improvement_hint"])
            # Score the retry — use it regardless of result
            quality = self._judge.score(subject=subject, body=body, profile=profile)
            if not quality["passed"]:
                log.warning(
                    f"[outreach] retry still below threshold (score={quality['overall_score']:.1f}) "
                    "— using anyway"
                )

        return subject, body, quality

    def _build_profile(self, lead: Lead, enrichment: Enrichment | None) -> dict:
        return {
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

    def _personalise(
        self,
        profile: dict,
        step: dict,
        improvement_hint: str = "",
    ) -> tuple[str, str]:
        """LLM personalisation. Falls back to template substitution on error."""
        if improvement_hint:
            prompt = _PERSONALISE_PROMPT_RETRY.format(
                profile_json=json.dumps(profile, indent=2),
                subject_template=step["subject_template"],
                body_template=step["body_template"],
                improvement_hint=improvement_hint,
            )
        else:
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
            subject = step["subject_template"].format(**{k: v or "" for k, v in profile.items()})
            body = step["body_template"].format(**{k: v or "" for k, v in profile.items()})
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
        # Demo mode: when SMTP is not configured, mark as "sent" so the
        # autonomy feed and outreach stats reflect real scheduled-sequence behaviour.
        if not settings.SMTP_HOST:
            email_record.status = "sent"
            email_record.sent_at = utcnow()
            db.commit()
            log.info(f"[outreach] Demo mode — email {email_record.id} marked sent (no SMTP)")
            return "sent_demo"

        # CAN-SPAM: every commercial email carries a working opt-out
        unsubscribe_url = (
            f"{settings.APP_BASE_URL}/unsubscribe/{email_record.id}"
            if settings.APP_BASE_URL else ""
        )
        plain_body = email_record.body
        if unsubscribe_url:
            plain_body += f"\n\n—\nDon't want to hear from us? Unsubscribe: {unsubscribe_url}"

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = email_record.subject
            msg["From"] = settings.OUTREACH_FROM_EMAIL
            msg["To"] = to_address
            if unsubscribe_url:
                msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
                msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            msg.attach(MIMEText(plain_body, "plain"))

            # HTML part with open-tracking pixel embedded
            # The pixel fires a GET /track/open/{email_id} which records the open
            # PRODUCTION: also wrap every link with /track/click/{id}?url=... for click tracking
            if settings.APP_BASE_URL:
                pixel_url = f"{settings.APP_BASE_URL}/track/open/{email_record.id}"
                html_body = (
                    f"<html><body><pre style='font-family:sans-serif'>{email_record.body}</pre>"
                    f"<p style='font-size:11px;color:#888'>Don't want to hear from us? "
                    f"<a href='{unsubscribe_url}'>Unsubscribe</a></p>"
                    f"<img src='{pixel_url}' width='1' height='1' style='display:none' /></body></html>"
                )
                msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.OUTREACH_FROM_EMAIL, [to_address], msg.as_string())

            email_record.status = "sent"
            email_record.sent_at = utcnow()
            db.commit()
            return "sent"

        except Exception as e:
            log.error(f"[outreach] SMTP send failed for {email_record.id}: {e}")
            email_record.status = "failed"
            email_record.error_message = str(e)
            db.commit()
            return f"failed: {e}"


# ---------------------------------------------------------------------------
# Scheduled follow-up sender (called by APScheduler every 15 min)
# ---------------------------------------------------------------------------

def send_pending_scheduled_emails(db: Session) -> dict:
    """
    Dispatch all OutreachEmail rows whose scheduled_at has passed and
    whose status is still 'scheduled'. This is what makes the multi-step
    sequence actually work — step 1 is sent immediately by the agent,
    steps 2 and 3 sit in the DB until this job picks them up.

    Guardrails applied before anything leaves the building:
      - global send window / weekday / daily-cap check (compliance.can_send_now)
      - per-lead: skip + cancel remaining steps if the lead has replied
      - per-lead: skip + cancel remaining steps if the address is suppressed

    Returns {"sent": int, "failed": int, "skipped": int, "cancelled": int, "reason": str | None}.
    """
    from app.services.compliance import (
        can_send_to_recipient,
        cancel_scheduled_emails,
        is_suppressed,
        lead_has_replied,
        sent_in_last_24h,
    )

    now = utcnow()
    from app.database.models import Lead as _Lead

    # Daily cap is global (protects the sending domain); the time-of-day
    # window is evaluated per recipient below, on their local clock.
    sent_24h = sent_in_last_24h(db)
    if sent_24h >= settings.OUTREACH_DAILY_SEND_LIMIT:
        reason = f"Daily send cap reached ({sent_24h}/{settings.OUTREACH_DAILY_SEND_LIMIT} in last 24h)"
        log.info(f"[outreach_scheduler] Holding sends — {reason}")
        return {"sent": 0, "failed": 0, "skipped": 0, "cancelled": 0, "reason": reason}

    pending = (
        db.query(OutreachEmail)
        .join(_Lead, OutreachEmail.lead_id == _Lead.id)
        .filter(
            OutreachEmail.status == "scheduled",
            OutreachEmail.scheduled_at <= now,
            _Lead.archived == False,  # noqa: E712
        )
        .limit(50)
        .all()
    )

    sent = failed = skipped = cancelled = 0
    _mode_cache: dict = {}
    agent = OutreachAgent()

    for email in pending:
        lead = db.query(_Lead).filter(_Lead.id == email.lead_id).first()
        if not lead or not lead.email:
            skipped += 1
            continue

        # Org flipped to draft-only mode after these were scheduled? Hold them.
        from app.services.tenancy import get_org_setting as _gos
        if lead.org_id not in _mode_cache:
            _mode_cache[lead.org_id] = _gos(db, lead.org_id, "autonomy_mode", settings.DEFAULT_AUTONOMY_MODE)
        if _mode_cache[lead.org_id] == "draft":
            skipped += 1
            continue

        # The lead answered — a human owns this thread now, stop the cadence
        if lead_has_replied(db, lead.id):
            cancelled += cancel_scheduled_emails(db, lead.id, "Lead replied — sequence stopped")
            continue

        # Never email suppressed addresses; kill the rest of their cadence too
        if is_suppressed(db, lead.email, org_id=lead.org_id):
            cancelled += cancel_scheduled_emails(db, lead.id, "Address on suppression list")
            continue

        # Recipient-local send window (falls back to global UTC window)
        window_ok, window_reason = can_send_to_recipient(lead, now)
        if not window_ok:
            log.debug(f"[outreach_scheduler] Holding {lead.email}: {window_reason}")
            skipped += 1
            continue

        if sent_24h + sent >= settings.OUTREACH_DAILY_SEND_LIMIT:
            skipped += 1
            continue

        result = agent._send_email(db, email, lead.email)
        if result.startswith("sent"):
            sent += 1
            log.info(
                f"[outreach_scheduler] Sent step {email.step_number} to "
                f"{lead.name} @ {lead.company} ({lead.email[:20]}…)"
            )
        else:
            failed += 1

    return {"sent": sent, "failed": failed, "skipped": skipped, "cancelled": cancelled, "reason": None}
