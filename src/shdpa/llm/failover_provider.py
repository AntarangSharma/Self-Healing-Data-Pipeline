"""LLM Provider Failover Wrapper.

Wraps a primary and fallback provider to achieve outage-resiliency.
"""
from __future__ import annotations

import structlog
from typing import Any

from shdpa.llm.provider import LLMProvider, LLMResponse

log = structlog.get_logger()


class FailoverProvider:
    """Outage-resilient LLM provider wrapper."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    @property
    def name(self) -> str:
        return self.primary.name

    @property
    def model(self) -> str:
        return self.primary.model

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.1,
        purpose: str = "",
    ) -> LLMResponse:
        try:
            return self.primary.complete(
                system, user, max_tokens=max_tokens, temperature=temperature, purpose=purpose
            )
        except Exception as e:
            log.warning(
                "provider.failover_triggered",
                primary=self.primary.name,
                fallback=self.fallback.name,
                error=str(e),
            )
            return self.fallback.complete(
                system, user, max_tokens=max_tokens, temperature=temperature, purpose=purpose
            )

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.0,
        purpose: str = "",
    ) -> tuple[dict[str, Any], LLMResponse]:
        try:
            return self.primary.complete_json(
                system, user, schema_hint=schema_hint, max_tokens=max_tokens, temperature=temperature, purpose=purpose
            )
        except Exception as e:
            log.warning(
                "provider.failover_triggered_json",
                primary=self.primary.name,
                fallback=self.fallback.name,
                error=str(e),
            )
            return self.fallback.complete_json(
                system, user, schema_hint=schema_hint, max_tokens=max_tokens, temperature=temperature, purpose=purpose
            )
