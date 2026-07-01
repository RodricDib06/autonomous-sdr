"""
Embedding Service + pgvector Semantic Memory Search

PoC: uses Ollama's embedding endpoint (free, local).
     Pull the model once: ollama pull nomic-embed-text
     Dimension: 768 for nomic-embed-text.

Falls back gracefully to keyword search in JSONB if:
  - Ollama is not running
  - The pgvector extension is not installed in Postgres
  - The embedding column has not been migrated yet

# PRODUCTION embedding alternatives:
#   OpenAI text-embedding-3-small (1536d, $0.02 / 1M tokens):
#     import openai
#     resp = openai.embeddings.create(input=text, model="text-embedding-3-small")
#     return resp.data[0].embedding
#
#   Anthropic does not yet offer an embeddings API — use OpenAI or Cohere.
#
#   Cohere embed-english-v3.0 (1024d, free tier 100 calls/min):
#     import cohere
#     co = cohere.Client(api_key)
#     resp = co.embed(texts=[text], model="embed-english-v3.0", input_type="search_document")
#     return resp.embeddings[0]
#
#   Voyage AI (1024d, 200M free tokens on signup):
#     import voyageai
#     vo = voyageai.Client(api_key)
#     result = vo.embed([text], model="voyage-2")
#     return result.embeddings[0]

# PRODUCTION pgvector setup:
#   1. Enable extension:    CREATE EXTENSION IF NOT EXISTS vector;
#   2. Add column:          ALTER TABLE conversations ADD COLUMN embedding vector(768);
#   3. Create HNSW index:   CREATE INDEX ON conversations USING hnsw (embedding vector_cosine_ops);
#   With the index, similarity search across millions of rows is sub-millisecond.
"""

import logging
import requests
from sqlalchemy.orm import Session
from app.config import settings

log = logging.getLogger(__name__)

# Dimension must match the Ollama model (nomic-embed-text = 768)
# Change to 1536 if switching to OpenAI text-embedding-3-small
EMBEDDING_DIM = 768
_OLLAMA_EMBED_URL = f"{settings.OLLAMA_BASE_URL}/api/embeddings"
_EMBED_MODEL = "nomic-embed-text"

# Cache to avoid re-embedding identical strings within a session
_embed_cache: dict[str, list[float]] = {}


def embed(text: str) -> list[float] | None:
    """
    Return a float vector for *text*, or None if embedding is unavailable.
    None return means the caller should fall back to keyword search.
    """
    if not text or not text.strip():
        return None

    text = text.strip()[:2000]  # cap to avoid oversized Ollama payloads

    if text in _embed_cache:
        return _embed_cache[text]

    try:
        resp = requests.post(
            _OLLAMA_EMBED_URL,
            json={"model": _EMBED_MODEL, "prompt": text},
            timeout=10,
        )
        resp.raise_for_status()
        vec = resp.json()["embedding"]
        _embed_cache[text] = vec
        return vec

    except Exception as e:
        log.debug(f"[embedding] Ollama unavailable ({e}) — falling back to keyword search")
        return None


def store_conversation_embedding(db: Session, conversation_id: str, text: str) -> bool:
    """
    Embed *text* (the conversation transcript) and persist it on the
    Conversation row's `embedding` column.

    Returns True if stored, False if pgvector or Ollama is unavailable.
    """
    vec = embed(text)
    if vec is None:
        return False

    try:
        db.execute(
            __import__("sqlalchemy").text(
                "UPDATE conversations SET embedding = :vec WHERE id = :id"
            ),
            {"vec": str(vec), "id": conversation_id},
        )
        db.commit()
        return True
    except Exception as e:
        log.debug(f"[embedding] pgvector store failed ({e}) — extension may not be enabled")
        db.rollback()
        return False


def semantic_search_conversations(
    db: Session,
    query: str,
    lead_id: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """
    Find conversations semantically similar to *query*.

    If pgvector is available: cosine similarity search on the embedding column.
    If not: falls back to ILIKE keyword search on the messages JSONB text.

    Returns list of dicts: {conversation_id, lead_id, channel, score, snippet}.
    """
    vec = embed(query)

    if vec is not None:
        try:
            results = _vector_search(db, vec, lead_id, limit)
            if results:
                return results
            # no embeddings stored yet — fall through to keyword search
        except Exception as e:
            log.warning(f"[embedding] Vector search failed ({e}), falling back to keyword")
            db.rollback()

    return _keyword_search(db, query, lead_id, limit)


def _vector_search(db: Session, vec: list[float], lead_id: str | None, limit: int) -> list[dict]:
    """Cosine similarity search using pgvector <=> operator."""
    vec_literal = f"'[{','.join(str(x) for x in vec)}]'::vector"
    lead_filter = f"AND c.lead_id = :lead_id" if lead_id else ""
    sql = f"""
        SELECT c.id, c.lead_id, c.channel, c.summary,
               1 - (c.embedding <=> {vec_literal}) AS similarity,
               c.created_at, l.name AS lead_name
        FROM conversations c
        JOIN leads l ON l.id = c.lead_id
        WHERE c.embedding IS NOT NULL
          {lead_filter}
        ORDER BY c.embedding <=> {vec_literal}
        LIMIT :limit
    """

    params: dict = {"limit": limit}
    if lead_id:
        params["lead_id"] = lead_id

    import sqlalchemy
    rows = db.execute(sqlalchemy.text(sql), params).fetchall()
    return [
        {
            "conversation_id": r[0],
            "lead_id": r[1],
            "channel": r[2],
            "snippet": (r[3] or "")[:200],
            "similarity": float(r[4]),
            "created_at": r[5].isoformat() if r[5] else None,
            "lead_name": r[6] or "",
            "search_type": "semantic",
        }
        for r in rows
    ]


def _keyword_search(db: Session, query: str, lead_id: str | None, limit: int) -> list[dict]:
    """Fallback: search conversation summaries, lead name/company by keyword."""
    import sqlalchemy as sa
    from app.database.models import Conversation, Lead
    q = db.query(Conversation, Lead.name).join(Lead, Lead.id == Conversation.lead_id)
    if lead_id:
        q = q.filter(Conversation.lead_id == lead_id)
    filtered = q
    if query:
        words = [w for w in query.lower().split() if len(w) > 3]
        if words:
            filtered = q.filter(sa.or_(
                *[Conversation.summary.ilike(f"%{w}%") for w in words],
                *[Lead.name.ilike(f"%{w}%") for w in words],
                *[Lead.company.ilike(f"%{w}%") for w in words],
            ))
    rows = filtered.limit(limit).all()
    # If no keyword hits, return all conversations so the UI always shows something
    if not rows:
        rows = q.limit(limit).all()
    return [
        {
            "conversation_id": r[0].id,
            "lead_id": r[0].lead_id,
            "channel": r[0].channel,
            "snippet": (r[0].summary or "")[:200],
            "similarity": None,
            "created_at": r[0].created_at.isoformat() if r[0].created_at else None,
            "lead_name": r[1] or "",
            "search_type": "keyword",
        }
        for r in rows
    ]
