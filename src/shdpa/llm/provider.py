"""Provider-agnostic LLM interface.

Selection: env var SHDPA_LLM_PROVIDER ∈ {mock, openai, anthropic, ollama}.
Each provider exposes the same `complete()` and `complete_json()` interface
so the agent never knows which one it's talking to.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int
    model: str
    provider: str


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.1,
        purpose: str = "",
    ) -> LLMResponse: ...

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.0,
        purpose: str = "",
    ) -> tuple[dict[str, Any], LLMResponse]: ...


def get_provider(name: str | None = None) -> LLMProvider:
    """Factory. Reads env if `name` not provided. Defaults to 'mock'."""
    name = (name or os.getenv("SHDPA_LLM_PROVIDER") or "mock").lower()

    if name == "mock":
        from shdpa.llm.mock_provider import MockProvider
        return MockProvider()
    if name == "openai":
        from shdpa.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()
    if name == "anthropic":
        from shdpa.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if name == "ollama":
        from shdpa.llm.ollama_provider import OllamaProvider
        return OllamaProvider()
    raise ValueError(f"Unknown LLM provider: {name!r}")
