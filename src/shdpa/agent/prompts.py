"""Prompt loader. Reads versioned prompts from /prompts/{version}/."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


@lru_cache(maxsize=32)
def load_prompt(name: str, version: str = "v1") -> str:
    p = PROMPTS_DIR / version / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"prompt not found: {p}")
    return p.read_text(encoding="utf-8")
