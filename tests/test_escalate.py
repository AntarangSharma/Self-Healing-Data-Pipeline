"""Tests for the Slack / PagerDuty escalation middleware."""

from __future__ import annotations

from typing import Any

import pytest

from shdpa.middleware import escalate as esc_mod
from shdpa.models import Incident


def _inc(**over) -> Incident:
    return Incident(
        dag_id="d",
        task_id="t",
        predicted_class="oom",
        predicted_class_confidence=0.55,
        exception_type="MemoryError",
        exception_message="boom",
        log_text="line1\nline2\nline3",
        **over,
    )


def test_no_channels_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("SHDPA_SLACK_WEBHOOK_URL", "SHDPA_PAGERDUTY_ROUTING_KEY", "SHDPA_ESCALATION_DRYRUN"):
        monkeypatch.delenv(k, raising=False)
    assert esc_mod.escalate(_inc(), reason="test") is False


def test_dryrun_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHDPA_ESCALATION_DRYRUN", "1")
    # even if Slack URL set, dryrun must not POST
    monkeypatch.setenv("SHDPA_SLACK_WEBHOOK_URL", "https://example.invalid/x")
    posted: list[Any] = []
    monkeypatch.setattr(esc_mod, "_post_json", lambda *a, **kw: posted.append(a) or True)
    assert esc_mod.escalate(_inc(), reason="r") is True
    assert posted == []


def test_slack_called_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHDPA_ESCALATION_DRYRUN", raising=False)
    monkeypatch.setenv("SHDPA_SLACK_WEBHOOK_URL", "https://hooks.slack/x")
    monkeypatch.delenv("SHDPA_PAGERDUTY_ROUTING_KEY", raising=False)
    calls: list[tuple[str, dict]] = []

    def fake(url: str, body: dict, timeout: float = 5.0) -> bool:
        calls.append((url, body))
        return True

    monkeypatch.setattr(esc_mod, "_post_json", fake)
    assert esc_mod.escalate(_inc(), reason="r") is True
    assert calls and calls[0][0] == "https://hooks.slack/x"
    assert "blocks" in calls[0][1]


def test_pagerduty_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHDPA_ESCALATION_DRYRUN", raising=False)
    monkeypatch.setenv("SHDPA_PAGERDUTY_ROUTING_KEY", "rk_dummy")
    monkeypatch.delenv("SHDPA_SLACK_WEBHOOK_URL", raising=False)
    captured: dict = {}

    def fake(url: str, body: dict, timeout: float = 5.0) -> bool:
        captured["url"] = url
        captured["body"] = body
        return True

    monkeypatch.setattr(esc_mod, "_post_json", fake)
    assert esc_mod.escalate(_inc(), reason="r") is True
    assert captured["url"] == "https://events.pagerduty.com/v2/enqueue"
    assert captured["body"]["routing_key"] == "rk_dummy"
    assert captured["body"]["event_action"] == "trigger"
    assert "summary" in captured["body"]["payload"]


def test_escalation_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent loop assumes escalate() never throws."""
    monkeypatch.delenv("SHDPA_ESCALATION_DRYRUN", raising=False)
    monkeypatch.setenv("SHDPA_SLACK_WEBHOOK_URL", "https://hooks.slack/x")

    def boom(*a, **kw):
        raise OSError("network down")

    monkeypatch.setattr(esc_mod, "_post_json", boom)
    # _post_json catches OSError internally and returns False, so escalate()
    # must report False without propagating.
    assert esc_mod.escalate(_inc(), reason="r") is False
