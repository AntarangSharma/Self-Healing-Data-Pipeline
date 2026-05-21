"""B2: single LLM call with logs pasted; no tools, no schema diff."""
from __future__ import annotations

import time

from shdpa.agent.prompts import load_prompt
from shdpa.llm.provider import LLMProvider, get_provider
from shdpa.middleware.cost_meter import CostMeter
from shdpa.models import Action, Incident, LLMCall


def run(incident: Incident, llm: LLMProvider | None = None) -> Incident:
    t0 = time.time()
    llm = llm or get_provider()
    meter = CostMeter()
    meter.reset_incident()

    user = (
        f"exception_type: {incident.exception_type or ''}\n"
        f"exception_message: {incident.exception_message or ''}\n\n"
        f"log (tail 60):\n" + "\n".join(incident.log_text.splitlines()[-60:])
    )
    system = load_prompt("triage") + "\n\nThen propose fix_kind."

    data, resp = llm.complete_json(
        system=system, user=user, purpose="b2_single_llm", max_tokens=400,
    )
    meter.record(resp)
    incident.predicted_class = data.get("failure_class", "unknown")
    incident.predicted_class_confidence = float(data.get("confidence", 0.0) or 0.0)
    incident.proposed_fix_kind = data.get("fix_kind", "noop")
    incident.proposed_fix_diff = ""  # no tools = no diff
    incident.proposed_files_changed = []
    incident.llm_calls.append(LLMCall(
        model=resp.model, provider=resp.provider,
        prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
        cost_usd=resp.cost_usd, latency_ms=resp.latency_ms, purpose="b2_single_llm",
    ))
    incident.actions.append(Action(kind="noop", payload={"policy": "B2"}, dry_run=True))
    incident.resolution_kind = "unresolved"
    incident.resolved = False
    incident.total_cost_usd = resp.cost_usd
    incident.total_latency_s = time.time() - t0
    return incident
