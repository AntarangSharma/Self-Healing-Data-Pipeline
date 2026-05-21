"""B0: restart-only. Never diagnoses; proposes 'retry' for everything."""
from __future__ import annotations

import time

from shdpa.models import Action, Incident


def run(incident: Incident) -> Incident:
    t0 = time.time()
    incident.predicted_class = "unknown"
    incident.predicted_class_confidence = 0.0
    incident.proposed_fix_kind = "retry"
    incident.proposed_fix_diff = ""
    incident.proposed_files_changed = []
    incident.actions.append(Action(kind="retry", payload={"policy": "B0"}, dry_run=False))
    incident.resolved = (
        incident.ground_truth is not None
        and incident.ground_truth.fix.kind == "retry"
    )
    incident.resolution_kind = "auto" if incident.resolved else "unresolved"
    incident.total_cost_usd = 0.0
    incident.total_latency_s = time.time() - t0
    return incident
