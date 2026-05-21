"""Prompt loader. Reads versioned prompts from /prompts/{version}/.

Version: pass `version=` explicitly, or set env var SHDPA_PROMPT_VERSION.
v1 is the stable initial release; v2 is real-LLM-tuned with per-class patch examples.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


@lru_cache(maxsize=32)
def load_prompt(name: str, version: str | None = None) -> str:
    version = version or os.getenv("SHDPA_PROMPT_VERSION", "v1")
    p = PROMPTS_DIR / version / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"prompt not found: {p}")
    return p.read_text(encoding="utf-8")
