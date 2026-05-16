"""
Conversational Agent

Handles multi-turn conversations with leads across channels: email replies,
live chat, SMS, and LinkedIn DMs.

PoC: persists conversation history in the DB and generates contextual replies
     using the LLM. SMS and LinkedIn channels are mocked with log output so
     the interface and message store work without paid subscriptions.

# PRODUCTION channel integrations:
#
#   SMS — Twilio:
#     pip install twilio
#     from twilio.rest import Client
#     client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
#     msg = client.messages.create(
#         body=reply_text,
#         from_=settings.TWILIO_PHONE_NUMBER,
#         to=lead_phone,
#     )
#     Receive inbound SMS via Twilio webhook: POST /webhooks/twilio/sms
#     Docs: https://www.twilio.com/docs/sms/api
#
#   LinkedIn DM — Unipile (most practical third-party bridge):
#     import requests
#     resp = requests.post(
#         "https://api2.unipile.com:13234/api/v1/chats/messages",
#         headers={"X-API-KEY": settings.UNIPILE_API_KEY},
#         json={"chat_id": linkedin_thread_id, "text": reply_text},
#     )
#     Receive inbound DMs via Unipile webhook: POST /webhooks/unipile/linkedin
#     Docs: https://developer.unipile.com/
#
#   Live Chat — Intercom:
#     Intercom sends conversation webhooks on new messages.
#     Reply via: POST https://api.intercom.io/conversations/{id}/reply
#     Docs: https://developers.intercom.com/docs/references/rest-api/api.intercom.io/Conversations/replyConversation/
#
#   Email replies — Postmark inbound or SendGrid Inbound Parse:
#     Route reply webhooks to POST /ingest/email, then call this agent
#     to continue the thread.
"""

import logging
from datetime import datetime
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.database.models import Lead, Enrichment, Verdict, Conversation
from app.database import crud
from app.services.providers import get_ai_client

log = logging.getLogger(__name__)

_REPLY_PROMPT = """You are a helpful, friendly B2B sales development representative (SDR).
You are having a conversation with a prospect. Keep replies concise (under 100 words),
warm, and focused on moving toward a discovery call or demo.

Lead context:
{lead_context}

Conversation history:
{history}

New message from lead:
{new_message}

Generate a reply that:
1. Acknowledges their message specifically
2. Provides value or answers their question
3. Moves toward booking a call if appropriate
4. Does NOT use generic sales buzzwords

Reply (plain text, no markdown):"""

_INITIATE_PROMPT = """You are a B2B SDR starting a live chat conversation with a lead who just visited the website.

Lead context:
{lead_context}

Write a short, friendly opening message (under 60 words) to start the conversation.
Mention something specific about their company or industry.
End with a simple open question.

Opening message (plain text only):"""


class ConversationalAgent(BaseAgent):
    """
    Generates contextual replies for any channel and persists the conversation thread.

    Supports two modes:
      - initiate: start a new outbound conversation
      - reply: respond to an inbound message from the lead
    """

    name = "conversational"

    def __init__(self):
        self._ai = get_ai_client()

    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        """
        input_data keys:
          channel:      "email" | "sms" | "chat" | "linkedin"
          mode:         "initiate" | "reply"
          message:      str — the lead's inbound message (for mode="reply")
          external_id:  str — Twilio SID / LinkedIn thread ID / etc. (optional)
        """
        lead = crud.get_lead(db, lead_id)
        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        channel = input_data.get("channel", "email")
        mode = input_data.get("mode", "reply")
        inbound_message = input_data.get("message", "")

        enrichment = (
            db.query(Enrichment).filter(Enrichment.lead_id == lead_id).first()
        )
        verdict = db.query(Verdict).filter(Verdict.lead_id == lead_id).first()

        # Get or create conversation thread for this lead+channel
        conversation = (
            db.query(Conversation)
            .filter(Conversation.lead_id == lead_id, Conversation.channel == channel)
            .first()
        )
        if not conversation:
            conversation = Conversation(
                lead_id=lead_id,
                channel=channel,
                messages=[],
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

        lead_context = self._build_context(lead, enrichment, verdict)

        if mode == "initiate":
            reply = self._generate_opener(lead_context)
        else:
            # Append inbound message to thread
            self._append_message(db, conversation, role="lead", content=inbound_message)
            history_text = self._format_history(conversation.messages[:-1])  # exclude just-added msg
            reply = self._generate_reply(lead_context, history_text, inbound_message)

        # Append agent reply to thread
        self._append_message(db, conversation, role="agent", content=reply)

        # Deliver to channel
        delivery = self._deliver(channel, lead, reply, input_data)

        return {
            "channel": channel,
            "reply": reply,
            "delivery": delivery,
            "conversation_id": conversation.id,
            "message_count": len(conversation.messages),
        }

    # ── LLM generation ──────────────────────────────────────────────────────

    def _generate_opener(self, lead_context: str) -> str:
        prompt = _INITIATE_PROMPT.format(lead_context=lead_context)
        try:
            return self._ai.generate(prompt).strip()
        except Exception as e:
            log.warning(f"[conversational] LLM opener failed: {e}")
            return "Hi! I noticed you stopped by — happy to answer any questions. What brings you here today?"

    def _generate_reply(self, lead_context: str, history: str, message: str) -> str:
        prompt = _REPLY_PROMPT.format(
            lead_context=lead_context,
            history=history,
            new_message=message,
        )
        try:
            return self._ai.generate(prompt).strip()
        except Exception as e:
            log.warning(f"[conversational] LLM reply failed: {e}")
            return "Thanks for your message! Let me look into that and get back to you shortly."

    # ── Channel delivery ────────────────────────────────────────────────────

    def _deliver(self, channel: str, lead: Lead, reply: str, input_data: dict) -> str:
        if channel == "sms":
            return self._send_sms(lead, reply, input_data)
        elif channel == "linkedin":
            return self._send_linkedin_dm(lead, reply, input_data)
        elif channel == "chat":
            # Chat is push-based — reply is returned in the response and the
            # frontend / WebSocket layer delivers it. Nothing to do server-side.
            return "delivered_via_websocket"
        else:
            # email — caller is responsible for sending via OutreachAgent / SMTP
            return "reply_generated_for_email"

    def _send_sms(self, lead: Lead, reply: str, input_data: dict) -> str:
        """
        PoC: log the SMS. In production, swap this body for Twilio.

        # PRODUCTION:
        #   from twilio.rest import Client
        #   client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        #   msg = client.messages.create(
        #       body=reply,
        #       from_=settings.TWILIO_PHONE_NUMBER,
        #       to=input_data.get("phone") or lead_phone_from_enrichment,
        #   )
        #   return msg.sid
        """
        phone = input_data.get("phone", "UNKNOWN")
        log.info(f"[conversational/sms] MOCK → {phone}: {reply[:80]}...")
        return "mock_sms_sent"

    def _send_linkedin_dm(self, lead: Lead, reply: str, input_data: dict) -> str:
        """
        PoC: log the LinkedIn DM. In production, use Unipile or Sales Navigator API.

        # PRODUCTION via Unipile:
        #   import requests
        #   resp = requests.post(
        #       "https://api2.unipile.com:13234/api/v1/chats/messages",
        #       headers={"X-API-KEY": settings.UNIPILE_API_KEY, "Content-Type": "application/json"},
        #       json={"chat_id": input_data.get("linkedin_thread_id"), "text": reply},
        #   )
        #   return resp.json().get("id", "unknown")
        """
        thread_id = input_data.get("linkedin_thread_id", "UNKNOWN")
        log.info(f"[conversational/linkedin] MOCK → thread={thread_id}: {reply[:80]}...")
        return "mock_linkedin_dm_sent"

    # ── Conversation helpers ─────────────────────────────────────────────────

    def _append_message(self, db: Session, conv: Conversation, role: str, content: str) -> None:
        messages = list(conv.messages or [])
        messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        })
        conv.messages = messages
        conv.updated_at = datetime.utcnow()
        db.commit()

    def _format_history(self, messages: list) -> str:
        if not messages:
            return "(no prior messages)"
        lines = []
        for m in messages[-10:]:  # last 10 messages for context window
            speaker = "Lead" if m["role"] == "lead" else "You"
            lines.append(f"{speaker}: {m['content']}")
        return "\n".join(lines)

    def _build_context(self, lead: Lead, enrichment, verdict) -> str:
        parts = [f"Name: {lead.name}", f"Company: {lead.company}", f"Email: {lead.email}"]
        if enrichment:
            parts += [
                f"Job Title: {enrichment.job_title}",
                f"Seniority: {enrichment.seniority}",
                f"Industry: {enrichment.industry}",
                f"Company Size: {enrichment.company_size}",
            ]
        if verdict:
            parts.append(f"Qualification: {verdict.final_verdict} (confidence {verdict.confidence_score:.0%})")
        return "\n".join(parts)
