from app.config import settings


def get_ai_client():
    """Return the configured AI client.

    Controlled by AI_PROVIDER env var:
      ollama  — default, free, requires local Ollama + a pulled model
      groq    — free tier (6 000 req/h), requires GROQ_API_KEY
      claude  — production quality, requires ANTHROPIC_API_KEY
    """
    if settings.AI_PROVIDER == "claude":
        from app.services.claude_client import ClaudeClient
        return ClaudeClient()
    if settings.AI_PROVIDER == "groq":
        from app.services.groq_client import GroqClient
        return GroqClient()
    from app.services.ollama_client import OllamaClient
    return OllamaClient()


def get_enrichment_provider():
    """Return the configured enrichment provider.

    Controlled by ENRICHMENT_PROVIDER env var:
      synthetic — default, free, domain heuristics
      hunter    — real company data via Hunter.io, requires HUNTER_API_KEY
      pdl       — People Data Labs, 100 free calls/month, requires PDL_API_KEY
    """
    if settings.ENRICHMENT_PROVIDER == "pdl":
        from app.services.enrichment.pdl import PDLEnrichmentProvider
        return PDLEnrichmentProvider()
    if settings.ENRICHMENT_PROVIDER == "hunter":
        from app.services.enrichment.hunter import HunterEnrichmentProvider
        return HunterEnrichmentProvider()
    from app.services.enrichment.synthetic import SyntheticEnrichmentProvider
    return SyntheticEnrichmentProvider()
