"""
Agent Memory Service

Provides a simple read/write interface over the `conversations` table so any
agent can store and retrieve conversation context without coupling to the ORM.

PoC: Postgres-backed, per-lead per-channel threads with an optional LLM summary.

# PRODUCTION alternatives for long-horizon memory:
#   - Redis with TTL: fast for session-scoped context (e.g. live chat threads)
#       r.setex(f"memory:{lead_id}:{channel}", 3600, json.dumps(messages))
#
#   - Pinecone / Weaviate / pgvector: semantic memory — retrieve the most
#       relevant past exchanges by embedding similarity rather than recency.
#       Useful when threads span months and you need "what did we discuss last time?"
#       pgvector is free and already in Postgres:
#         CREATE EXTENSION IF NOT EXISTS vector;
#         ALTER TABLE conversations ADD COLUMN embedding vector(1536);
#
#   - LangChain ConversationBufferWindowMemory / SummaryBufferMemory:
#       Drop-in classes that handle trimming and summarisation automatically.
#       Docs: https://python.langchain.com/docs/modules/memory/
"""

import logging
from sqlalchemy.orm import Session

from app.database.models import Conversation
from app.services.providers import get_ai_client
from app.utils.time import utcnow

log = logging.getLogger(__name__)

_SUMMARY_PROMPT = """Summarise the following sales conversation in 2–3 sentences.
Focus on: what the lead asked, any objections raised, and the current stage (e.g. interested, needs more info, booked a call).

Conversation:
{history}

Summary (plain text):"""


def get_or_create_conversation(db: Session, lead_id: str, channel: str) -> Conversation:
    conv = (
        db.query(Conversation)
        .filter(Conversation.lead_id == lead_id, Conversation.channel == channel)
        .first()
    )
    if not conv:
        conv = Conversation(lead_id=lead_id, channel=channel, messages=[])
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv


def append_message(db: Session, conv: Conversation, role: str, content: str) -> None:
    """Add a message to the thread and persist."""
    messages = list(conv.messages or [])
    messages.append({
        "role": role,
        "content": content,
        "timestamp": utcnow().isoformat(),
    })
    conv.messages = messages
    conv.updated_at = utcnow()
    db.commit()


def get_recent_messages(conv: Conversation, n: int = 10) -> list[dict]:
    """Return the last n messages from the thread."""
    return (conv.messages or [])[-n:]


def format_history(conv: Conversation, n: int = 10) -> str:
    """Format last n messages as a plain-text transcript."""
    messages = get_recent_messages(conv, n)
    if not messages:
        return "(no prior messages)"
    lines = []
    for m in messages:
        speaker = "Lead" if m["role"] == "lead" else "Agent"
        lines.append(f"{speaker}: {m['content']}")
    return "\n".join(lines)


def summarise_conversation(db: Session, conv: Conversation) -> str:
    """
    Generate and persist an LLM summary of the conversation, then embed it
    for semantic search via pgvector.
    Returns the summary string.
    """
    history = format_history(conv, n=20)
    if history == "(no prior messages)":
        return ""

    ai = get_ai_client()
    prompt = _SUMMARY_PROMPT.format(history=history)
    try:
        summary = ai.generate(prompt).strip()
        conv.summary = summary
        conv.updated_at = utcnow()
        db.commit()

        # Embed the summary for semantic search (no-op if Ollama / pgvector unavailable)
        from app.services.embedding_service import store_conversation_embedding
        store_conversation_embedding(db, conv.id, summary)

        return summary
    except Exception as e:
        log.warning(f"[memory] Summarisation failed for conversation {conv.id}: {e}")
        return ""


def get_all_conversations(db: Session, lead_id: str) -> list[Conversation]:
    return (
        db.query(Conversation)
        .filter(Conversation.lead_id == lead_id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
