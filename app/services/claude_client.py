import logging
from app.config import settings

log = logging.getLogger(__name__)

# System prompt cached across every call — Anthropic charges zero tokens
# for cache hits after the first request.
_SYSTEM_PROMPT = (
    "You are a helpful AI assistant specialised in B2B sales qualification. "
    "Always respond with valid JSON exactly as instructed. "
    "Never add markdown fences, prose, or any text outside the JSON object."
)


class ClaudeClient:
    """Drop-in replacement for OllamaClient backed by the Anthropic Claude API.

    Mirrors the generate() interface so agents require zero changes beyond
    swapping providers via AI_PROVIDER=claude in the environment.
    """

    def __init__(self, model: str = None):
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "anthropic package is required for AI_PROVIDER=claude. "
                "Run: pip install anthropic"
            ) from exc

        if not settings.ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Add it to your .env file to use AI_PROVIDER=claude."
            )

        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = model or settings.ANTHROPIC_MODEL

    def generate(self, prompt: str) -> str:
        """Send a prompt and return the text response.

        The system prompt uses prompt caching (cache_control=ephemeral) so
        repeated calls within the 5-minute TTL window are significantly cheaper.
        """
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
