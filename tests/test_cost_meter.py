"""Cost-meter safety tests.

The single most important safety claim of this project is that an LLM-agent
loop CANNOT silently run up an unbounded bill. These tests verify the hard
cap actually trips and that the agent halts cleanly when it does.
"""
from __future__ import annotations

import pytest

from shdpa.llm.provider import LLMResponse
from shdpa.middleware.cost_meter import CostBudgetExceeded, CostMeter


def _fake_resp(cost: float) -> LLMResponse:
    return LLMResponse(
        text="",
        prompt_tokens=10,
        completion_tokens=10,
        cost_usd=cost,
        latency_ms=1,
        model="test",
        provider="test",
    )


def test_under_cap_records_normally() -> None:
    m = CostMeter(per_incident_cap=0.10, total_cap=1.00)
    m.record(_fake_resp(0.03))
    m.record(_fake_resp(0.03))
    assert m.incident_spend == pytest.approx(0.06)
    assert m.total_spend == pytest.approx(0.06)


def test_per_incident_cap_trips() -> None:
    m = CostMeter(per_incident_cap=0.05, total_cap=10.00)
    m.record(_fake_resp(0.03))  # ok
    with pytest.raises(CostBudgetExceeded, match="per-incident cap"):
        m.record(_fake_resp(0.04))  # would push to 0.07 > 0.05


def test_total_cap_trips() -> None:
    m = CostMeter(per_incident_cap=10.00, total_cap=0.10)
    m.record(_fake_resp(0.05))
    m.reset_incident()
    m.record(_fake_resp(0.04))
    m.reset_incident()
    with pytest.raises(CostBudgetExceeded, match="total cap"):
        m.record(_fake_resp(0.05))  # would push total to 0.14 > 0.10


def test_reset_incident_clears_only_incident() -> None:
    m = CostMeter(per_incident_cap=10.00, total_cap=10.00)
    m.record(_fake_resp(0.05))
    assert m.incident_spend == pytest.approx(0.05)
    assert m.total_spend == pytest.approx(0.05)
    m.reset_incident()
    assert m.incident_spend == 0.0
    assert m.total_spend == pytest.approx(0.05)


def test_cap_trips_exactly_at_boundary() -> None:
    """At exactly the cap value we do NOT trip (> not >=). Above does."""
    m = CostMeter(per_incident_cap=0.05, total_cap=10.00)
    m.record(_fake_resp(0.05))  # equal, allowed
    assert m.incident_spend == pytest.approx(0.05)
    with pytest.raises(CostBudgetExceeded):
        m.record(_fake_resp(0.001))


def test_cost_meter_halts_agent_loop_cleanly() -> None:
    """End-to-end: cost-meter exception bubbles out of run_agent → noop action.

    This is the production-safety claim: even if the LLM is buggy or the cost
    estimate is wrong, the agent stops and reports rather than racking up bills.
    """
    from shdpa.models import Incident
    from shdpa.agent.loop import run_agent

    inc = Incident(
        source="replay",
        log_text="generic failure",
        dag_id="d", task_id="t", run_id="r",
    )
    meter = CostMeter(per_incident_cap=0.000001, total_cap=10.00)  # impossibly small
    out = run_agent(inc, meter=meter)
    # The agent should either record an error or terminate with a noop action.
    # Either way the run finished cleanly without raising.
    assert out.error is not None or any(a.kind == "noop" for a in out.actions)
