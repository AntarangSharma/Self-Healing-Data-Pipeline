"""Escalation — what to do when the agent CAN'T auto-fix.

The original README claimed "non-whitelisted classes escalate to humans."
For a long time that meant emitting `kind="noop"` and logging a line.
This module is what makes the claim actually true.

Supported channels (set the env var to enable):
  - SHDPA_SLACK_WEBHOOK_URL  — POST a structured incoming-webhook payload
  - SHDPA_PAGERDUTY_ROUTING_KEY — POST a v2 Events API payload
  - SHDPA_ESCALATION_DRYRUN=1 — print to stderr instead, even if URLs set

If no env var is set, the call logs a structlog event with level=warning
and returns False so callers can decide to fail loudly.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import structlog

from shdpa.models import Incident

log = structlog.get_logger()


def _build_payload(incident: Incident, reason: str) -> dict[str, Any]:
    return {
        "incident_id": str(incident.id),
        "dag_id": incident.dag_id,
        "task_id": incident.task_id,
        "predicted_class": incident.predicted_class,
        "confidence": incident.predicted_class_confidence,
        "root_cause": incident.root_cause_summary,
        "exception_type": incident.exception_type,
        "exception_message": incident.exception_message,
        "log_tail": "\n".join(incident.log_text.splitlines()[-20:]),
        "reason_for_escalation": reason,
        "total_cost_usd": incident.total_cost_usd,
        "actions": [{"kind": a.kind, "blocked_by": a.blocked_by_guardrail}
                    for a in incident.actions],
    }


def _slack_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": (
            f":rotating_light: *shdpa escalation*: "
            f"`{payload['predicted_class']}` on "
            f"`{payload['dag_id']}.{payload['task_id']}`"
        ),
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text":
                f":rotating_light: *shdpa escalation* — `{payload['predicted_class']}` "
                f"(confidence {payload['confidence']:.2f})\n"
                f"*DAG*: `{payload['dag_id']}` *Task*: `{payload['task_id']}`\n"
                f"*Reason*: {payload['reason_for_escalation']}\n"
                f"*Root cause*: {payload['root_cause'] or '(none)'}\n"
                f"*Exception*: `{payload['exception_type']}`: "
                f"{payload['exception_message'] or '(none)'}",
            }},
            {"type": "section", "text": {"type": "mrkdwn", "text":
                "```\n" + payload["log_tail"][:1500] + "\n```"
            }},
        ],
    }


def _pagerduty_body(payload: dict[str, Any], routing_key: str) -> dict[str, Any]:
    return {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": payload["incident_id"],
        "payload": {
            "summary": (
                f"shdpa: {payload['predicted_class']} on "
                f"{payload['dag_id']}.{payload['task_id']}"
            ),
            "severity": "warning",
            "source": "shdpa-agent",
            "custom_details": payload,
        },
    }


def _post_json(url: str, body: dict[str, Any], timeout: float = 5.0) -> bool:
    try:
        req = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (URLError, OSError) as e:
        log.warning("escalation.webhook_failed", url=url, error=repr(e))
        return False


def escalate(incident: Incident, *, reason: str) -> bool:
    """Send escalation to whatever channel(s) are configured.

    Returns True if at least one channel acknowledged the message.
    Always non-throwing — escalation failure must NOT bring down the
    agent loop. (If escalation is down AND the agent is down, you're
    having a really bad day either way.)
    """
    payload = _build_payload(incident, reason)
    if os.getenv("SHDPA_ESCALATION_DRYRUN", "0") == "1":
        log.warning("escalation.dryrun", **payload)
        return True

    delivered = False

    def _safe_post(url: str, body: dict[str, Any]) -> bool:
        # Defensive wrapper: escalation MUST NOT raise into the agent loop,
        # even if a monkeypatched / misbehaving _post_json throws.
        try:
            return _post_json(url, body)
        except Exception as e:  # noqa: BLE001
            log.warning("escalation.unexpected_error", url=url, error=repr(e))
            return False

    slack_url = os.getenv("SHDPA_SLACK_WEBHOOK_URL")
    if slack_url and _safe_post(slack_url, _slack_body(payload)):
        log.info("escalation.slack_ok", incident_id=payload["incident_id"])
        delivered = True

    pd_key = os.getenv("SHDPA_PAGERDUTY_ROUTING_KEY")
    if pd_key and _safe_post("https://events.pagerduty.com/v2/enqueue",
                  _pagerduty_body(payload, pd_key)):
        log.info("escalation.pagerduty_ok", incident_id=payload["incident_id"])
        delivered = True

    if not (slack_url or pd_key):
        log.warning(
            "escalation.no_channel_configured",
            incident_id=payload["incident_id"],
            reason=reason,
            hint="Set SHDPA_SLACK_WEBHOOK_URL or SHDPA_PAGERDUTY_ROUTING_KEY",
        )

    return delivered
