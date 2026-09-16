"""
Agents must resolve their LLM through the provider factory.

AnalysisAgent and ValidatorAgent each constructed `OllamaClient()` directly,
with a comment noting it should be `get_ai_client()` one day. That made
AI_PROVIDER decorative: a deployment configured for Groq still dialled
localhost:11434. In production the validator failed on every lead and the
pipeline finished with no verdict at all, while /health happily reported
`ai_provider: groq`.

The factory also wraps clients in TrackedAIClient, so bypassing it silently
disabled the per-call token/cost/latency telemetry the ROI panel is built on.
"""

import pytest

from app.agents.analysis_agent import AnalysisAgent
from app.agents.validator_agent import ValidatorAgent
from app.services.llm_tracker import TrackedAIClient
from app.services.ollama_client import OllamaClient


AGENTS = [AnalysisAgent, ValidatorAgent]


@pytest.mark.parametrize("agent_cls", AGENTS)
def test_agent_uses_the_tracked_provider_client(agent_cls):
    # Whatever the configured provider, the client must come from the factory
    # so calls are metered.
    agent = agent_cls()
    assert isinstance(agent._llm, TrackedAIClient), (
        f"{agent_cls.__name__} bypassed get_ai_client(), so its LLM calls are unmetered"
    )


@pytest.mark.parametrize("agent_cls", AGENTS)
def test_agent_honours_ai_provider(agent_cls, monkeypatch):
    monkeypatch.setattr("app.config.settings.AI_PROVIDER", "groq")
    monkeypatch.setattr("app.config.settings.GROQ_API_KEY", "test-key", raising=False)

    agent = agent_cls()
    inner = getattr(agent._llm, "_client", None) or getattr(agent._llm, "client", None)
    assert inner is not None, "TrackedAIClient no longer exposes its wrapped client"
    assert not isinstance(inner, OllamaClient), (
        f"{agent_cls.__name__} built an Ollama client while AI_PROVIDER=groq — "
        "it is not going through the provider factory"
    )
