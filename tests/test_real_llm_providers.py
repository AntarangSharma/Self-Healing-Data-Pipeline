"""Integration tests for real LLM providers.

These tests are SKIPPED by default. They only run when the relevant API key
env var is present, so they cost $0 in CI and ~$0.005 when run locally.

Purpose: prove the provider abstraction actually works end-to-end on a real
model — not just on the deterministic mock — without burning credits on
every CI build.

Run locally:
  ANTHROPIC_API_KEY=sk-... pytest tests/test_real_llm_providers.py -v
  OPENAI_API_KEY=sk-...    pytest tests/test_real_llm_providers.py -v
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from shdpa.agent.loop import run_agent
from shdpa.chaos import generate_fixture
from shdpa.eval.fixture import load_fixture
from shdpa.eval.metrics import score_incident
from shdpa.llm.provider import get_provider
from shdpa.middleware.cost_meter import CostMeter


# --------- provider smoke tests (one LLM call each) ----------

@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live anthropic provider test",
)
def test_anthropic_provider_returns_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """One real Claude call. Verifies JSON-mode round-trip and pricing math."""
    monkeypatch.setenv("SHDPA_LLM_PROVIDER", "anthropic")
    llm = get_provider()
    data, resp = llm.complete_json(
        system="You return one JSON object with key 'ok' set to true.",
        user="return ok",
        purpose="integration_test",
        max_tokens=64,
    )
    assert isinstance(data, dict)
    assert resp.cost_usd >= 0, "cost must be non-negative"
    assert resp.prompt_tokens > 0
    assert resp.completion_tokens > 0
    assert resp.provider == "anthropic"


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skipping live openai provider test",
)
def test_openai_provider_returns_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """One real OpenAI call. Same contract as the anthropic test."""
    monkeypatch.setenv("SHDPA_LLM_PROVIDER", "openai")
    llm = get_provider()
    data, resp = llm.complete_json(
        system="You return one JSON object with key 'ok' set to true.",
        user="return ok",
        purpose="integration_test",
        max_tokens=64,
    )
    assert isinstance(data, dict)
    assert resp.cost_usd >= 0
    assert resp.provider == "openai"


# --------- agent end-to-end on one fixture per provider ----------

@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
def test_anthropic_agent_resolves_schema_rename(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: real Claude must triage + fix one schema_rename fixture.

    Cost: ~$0.01. Asserts class accuracy AND fix correctness — if the model
    regresses on the simplest case, this catches it.
    """
    monkeypatch.setenv("SHDPA_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("SHDPA_PROMPT_VERSION", "v3")
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "schema_rename"
        generate_fixture("schema_rename_column", out, seed=0)
        incident = load_fixture(out)
        # belt-and-suspenders cost cap so a buggy run can't burn >5¢
        meter = CostMeter(per_incident_cap=0.05, total_cap=0.10)
        incident = run_agent(incident, meter=meter)
        score = score_incident(incident)
        assert score.class_correct, (
            f"triage misclassified: predicted={incident.predicted_class}"
        )
        assert score.resolved or score.fix_correct, (
            f"agent did not produce a valid fix: actions={incident.actions}"
        )
        assert not score.hallucinated, "real LLM hallucinated a column name"
    finally:
        shutil.rmtree(tmp)


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)
def test_openai_agent_resolves_schema_rename(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same end-to-end check on OpenAI. Cost: ~$0.005 on gpt-4o-mini."""
    monkeypatch.setenv("SHDPA_LLM_PROVIDER", "openai")
    monkeypatch.setenv("SHDPA_PROMPT_VERSION", "v3")
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / "schema_rename"
        generate_fixture("schema_rename_column", out, seed=0)
        incident = load_fixture(out)
        meter = CostMeter(per_incident_cap=0.05, total_cap=0.10)
        incident = run_agent(incident, meter=meter)
        score = score_incident(incident)
        assert score.class_correct
        assert not score.hallucinated
    finally:
        shutil.rmtree(tmp)
