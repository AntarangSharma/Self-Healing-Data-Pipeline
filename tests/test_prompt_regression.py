"""Prompt-set regression guard.

Why: the v2 → v3 prompt change accidentally introduced a regression on
schema_drift (50 % resolved instead of 100 %) before it was caught. Going
forward, any prompt edit must keep mock-eval at ≥ 85 % resolved across the
20-fixture chaos set. The mock provider runs in ≈ 1 s with $0 cost, so this
check belongs in the default pytest suite.

If you change a prompt and this test fails, fix the prompt or update the
threshold deliberately — do not silently lower it.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from shdpa.agent.loop import run_agent
from shdpa.chaos import INJECTORS, generate_fixture
from shdpa.eval.fixture import load_fixture
from shdpa.eval.metrics import score_incident

# Mock provider gets 100% on the synthetic set; we leave a small margin so a
# legitimate refactor doesn't fail just from non-determinism in one class.
RESOLVED_THRESHOLD = 0.85
CLASS_ACC_THRESHOLD = 0.95


@pytest.mark.parametrize("prompt_version", ["v3"])
def test_prompt_set_meets_threshold(
    prompt_version: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHDPA_LLM_PROVIDER", "mock")
    monkeypatch.setenv("SHDPA_PROMPT_VERSION", prompt_version)
    # Clear any persistence env so we don't write to disk
    monkeypatch.delenv("SHDPA_STORAGE_PATH", raising=False)
    monkeypatch.delenv("SHDPA_ALLOWED_REPOS", raising=False)

    tmp = Path(tempfile.mkdtemp())
    try:
        kinds = list(INJECTORS.keys())
        scores: list[bool] = []
        class_correct: list[bool] = []
        for kind in kinds:
            out = tmp / kind
            generate_fixture(kind, out, seed=0)
            incident = load_fixture(out)
            incident = run_agent(incident)
            s = score_incident(incident)
            scores.append(bool(s.resolved))
            class_correct.append(bool(s.class_correct))
        resolved_rate = sum(scores) / len(scores)
        class_rate = sum(class_correct) / len(class_correct)
        assert resolved_rate >= RESOLVED_THRESHOLD, (
            f"prompt regression: {prompt_version} resolved "
            f"{resolved_rate:.0%} < {RESOLVED_THRESHOLD:.0%} threshold"
        )
        assert class_rate >= CLASS_ACC_THRESHOLD, (
            f"prompt regression: {prompt_version} class accuracy "
            f"{class_rate:.0%} < {CLASS_ACC_THRESHOLD:.0%} threshold"
        )
    finally:
        shutil.rmtree(tmp)
