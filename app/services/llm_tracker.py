"""
LLM cost & latency tracking.

Every `generate()` through `get_ai_client()` records an LLMCall row:
provider, model, token counts (estimated at ~4 chars/token when the
provider doesn't report usage), dollar cost, latency, and — when the call
happens inside an agent's `_timed_run` — the lead and agent it served.

This is what makes "this lead cost $0.04 to qualify" and the ROI panel
possible, and it's the first thing you need operationally when an agent
loop starts burning tokens.
"""

import logging
import time
from contextvars import ContextVar

log = logging.getLogger(__name__)

# (lead_id, agent_name) attribution for calls made inside an agent run
_llm_context: ContextVar[tuple[str | None, str | None]] = ContextVar(
    "llm_context", default=(None, None)
)

# USD per 1M tokens: (input, output). Prefix-matched against the model name.
PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "llama-3.1-70b": (0.59, 0.79),
    "llama-3.3-70b": (0.59, 0.79),
    "llama3": (0.0, 0.0),          # local via Ollama
    "mixtral": (0.24, 0.24),
    "mistral": (0.0, 0.0),         # local via Ollama
    "claude-fable-5": (20.0, 100.0),
    "claude-opus": (15.0, 75.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (1.0, 5.0),
}


def set_llm_context(lead_id: str | None, agent_name: str | None):
    return _llm_context.set((lead_id, agent_name))


def reset_llm_context(token) -> None:
    _llm_context.reset(token)


def estimate_tokens(text: str) -> int:
    """~4 characters per token — close enough for cost telemetry."""
    return max(1, len(text or "") // 4)


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    model = (model or "").lower()
    for prefix, (in_price, out_price) in PRICING_PER_MTOK.items():
        if model.startswith(prefix):
            return (prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000
    return 0.0


def record_llm_call(
    provider: str,
    model: str,
    prompt: str,
    completion: str,
    latency_ms: int,
    success: bool = True,
    error: str | None = None,
) -> None:
    """Persist one call on a dedicated short-lived session. Never raises."""
    try:
        from app.database.connection import SessionLocal
        from app.database.models import LLMCall

        lead_id, agent_name = _llm_context.get()
        pt = estimate_tokens(prompt)
        ct = estimate_tokens(completion)

        db = SessionLocal()
        try:
            db.add(LLMCall(
                lead_id=lead_id,
                agent_name=agent_name,
                provider=provider,
                model=model,
                prompt_tokens=pt,
                completion_tokens=ct,
                cost_usd=cost_usd(model, pt, ct),
                latency_ms=latency_ms,
                success=success,
                error_message=(error or "")[:500] or None,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        log.debug(f"[llm_tracker] Failed to record call: {e}")


class TrackedAIClient:
    """
    Transparent wrapper around any AI client exposing `generate(prompt)`.
    Streaming and batch paths pass through untracked (they're preview-only).
    """

    def __init__(self, inner, provider: str):
        self._inner = inner
        self._provider = provider

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", self._provider)

    def generate(self, prompt: str, *args, **kwargs) -> str:
        start = time.time()
        try:
            result = self._inner.generate(prompt, *args, **kwargs)
        except Exception as e:
            record_llm_call(
                self._provider, self.model, prompt, "",
                int((time.time() - start) * 1000), success=False, error=str(e),
            )
            raise
        record_llm_call(
            self._provider, self.model, prompt, result or "",
            int((time.time() - start) * 1000),
        )
        return result

    async def generate_async(self, prompt: str, *args, **kwargs) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.generate(prompt, *args, **kwargs))

    def __getattr__(self, name):
        # stream_generate, generate_batch, model-specific extras
        return getattr(self._inner, name)
