"""Anthropic provider. Requires `pip install anthropic` + ANTHROPIC_API_KEY."""
from __future__ import annotations

import json
import os
import time
from typing import Any

from shdpa.llm.provider import LLMResponse

PRICING: dict[str, tuple[float, float]] = {
    "claude-3-5-haiku-latest": (0.80, 4.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-5-sonnet-latest": (3.00, 15.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-haiku-4-20250514": (1.00, 5.00),
}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError("Install with: pip install '.[anthropic]'") from e
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self.client = Anthropic()
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")

    def _price(self, pt: int, ct: int) -> float:
        rate_in, rate_out = PRICING.get(self.model, (1.0, 5.0))
        return (pt * rate_in + ct * rate_out) / 1_000_000

    def complete(
        self, system: str, user: str, *, max_tokens: int = 1024,
        temperature: float = 0.1, purpose: str = "",
    ) -> LLMResponse:
        t0 = time.time()
        r = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in r.content if hasattr(b, "text"))
        pt = r.usage.input_tokens
        ct = r.usage.output_tokens
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
        sys2 = system + "\n\nReturn ONLY a single JSON object, no prose. " + (schema_hint or "")
        resp = self.complete(sys2, user, max_tokens=max_tokens, temperature=temperature, purpose=purpose)
        text = resp.text.strip()
        # tolerate ```json fences
        if text.startswith("```"):
            text = text.strip("`")
            text = text.lstrip("json").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # try to find a {...} substring
            import re as _re
            m = _re.search(r"\{.*\}", text, _re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
        return data, resp
