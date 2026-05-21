"""OpenAI provider. Requires `pip install openai` + OPENAI_API_KEY."""
from __future__ import annotations

import json
import os
import time
from typing import Any

from shdpa.llm.provider import LLMResponse

# Per-MTok pricing (USD). Update as needed.
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
}


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("Install with: pip install '.[openai]'") from e
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY not set")
        self.client = OpenAI()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _price(self, pt: int, ct: int) -> float:
        rate_in, rate_out = PRICING.get(self.model, (1.0, 3.0))
        return (pt * rate_in + ct * rate_out) / 1_000_000

    def complete(
        self, system: str, user: str, *, max_tokens: int = 1024,
        temperature: float = 0.1, purpose: str = "",
    ) -> LLMResponse:
        t0 = time.time()
        r = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = r.choices[0].message.content or ""
        pt = r.usage.prompt_tokens if r.usage else 0
        ct = r.usage.completion_tokens if r.usage else 0
        return LLMResponse(
            text=text, prompt_tokens=pt, completion_tokens=ct,
            cost_usd=self._price(pt, ct),
            latency_ms=int((time.time() - t0) * 1000),
            model=self.model, provider=self.name,
        )

    def complete_json(
        self, system: str, user: str, *, schema_hint: str = "",
        max_tokens: int = 1024, temperature: float = 0.0, purpose: str = "",
    ) -> tuple[dict[str, Any], LLMResponse]:
        t0 = time.time()
        sys2 = system + "\n\nReturn ONLY valid JSON. " + (schema_hint or "")
        r = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": sys2}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        text = r.choices[0].message.content or "{}"
        pt = r.usage.prompt_tokens if r.usage else 0
        ct = r.usage.completion_tokens if r.usage else 0
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}
        resp = LLMResponse(
            text=text, prompt_tokens=pt, completion_tokens=ct,
            cost_usd=self._price(pt, ct),
            latency_ms=int((time.time() - t0) * 1000),
            model=self.model, provider=self.name,
        )
        return data, resp
