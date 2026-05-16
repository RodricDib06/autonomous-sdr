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
        return _vector_search(db, vec, lead_id, limit)
    else:
        return _keyword_search(db, query, lead_id, limit)


def _vector_search(db: Session, vec: list[float], lead_id: str | None, limit: int) -> list[dict]:
    """Cosine similarity search using pgvector <=> operator."""
    try:
        sql = """
            SELECT id, lead_id, channel, summary,
                   1 - (embedding <=> :vec::vector) AS score
            FROM conversations
            WHERE embedding IS NOT NULL
              {lead_filter}
            ORDER BY embedding <=> :vec::vector
            LIMIT :limit
        """.format(lead_filter="AND lead_id = :lead_id" if lead_id else "")

        params: dict = {"vec": str(vec), "limit": limit}
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
                "score": float(r[4]),
                "search_type": "semantic",
            }
            for r in rows
        ]
    except Exception as e:
        log.warning(f"[embedding] Vector search failed ({e}), falling back to keyword")
        return _keyword_search(db, "", lead_id, limit)


def _keyword_search(db: Session, query: str, lead_id: str | None, limit: int) -> list[dict]:
    """Fallback: search conversation summaries and JSONB message content by keyword."""
    from app.database.models import Conversation
    q = db.query(Conversation)
    if lead_id:
        q = q.filter(Conversation.lead_id == lead_id)
    if query:
        q = q.filter(Conversation.summary.ilike(f"%{query}%"))
    rows = q.limit(limit).all()
    return [
        {
            "conversation_id": r.id,
            "lead_id": r.lead_id,
            "channel": r.channel,
            "snippet": (r.summary or "")[:200],
            "score": 1.0,
            "search_type": "keyword",
        }
        for r in rows
    ]
