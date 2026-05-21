"""Ollama provider. Local models. Requires Ollama running on OLLAMA_HOST."""
from __future__ import annotations

import json
import os
import time
from typing import Any

from shdpa.llm.provider import LLMResponse


class OllamaProvider:
    name = "ollama"

    def __init__(self) -> None:
        try:
            import ollama
        except ImportError as e:
            raise RuntimeError("Install with: pip install '.[ollama]'") from e
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.client = ollama.Client(host=host)
        self.model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    def complete(
        self, system: str, user: str, *, max_tokens: int = 1024,
        temperature: float = 0.1, purpose: str = "",
    ) -> LLMResponse:
        t0 = time.time()
        r = self.client.chat(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            options={"temperature": temperature, "num_predict": max_tokens},
        )
        text = r["message"]["content"]
        pt = r.get("prompt_eval_count", 0)
        ct = r.get("eval_count", 0)
        return LLMResponse(
            text=text, prompt_tokens=pt, completion_tokens=ct,
            cost_usd=0.0,  # local
            latency_ms=int((time.time() - t0) * 1000),
            model=self.model, provider=self.name,
        )

    def complete_json(
        self, system: str, user: str, *, schema_hint: str = "",
        max_tokens: int = 1024, temperature: float = 0.0, purpose: str = "",
    ) -> tuple[dict[str, Any], LLMResponse]:
        sys2 = system + "\n\nReturn ONLY a JSON object. " + (schema_hint or "")
        t0 = time.time()
        r = self.client.chat(
            model=self.model,
            messages=[{"role": "system", "content": sys2}, {"role": "user", "content": user}],
            options={"temperature": temperature, "num_predict": max_tokens},
            format="json",
        )
        text = r["message"]["content"]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}
        pt = r.get("prompt_eval_count", 0)
        ct = r.get("eval_count", 0)
        resp = LLMResponse(
            text=text, prompt_tokens=pt, completion_tokens=ct,
            cost_usd=0.0,
            latency_ms=int((time.time() - t0) * 1000),
            model=self.model, provider=self.name,
        )
        return data, resp
