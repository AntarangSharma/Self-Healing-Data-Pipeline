"""B1: regex rules → templated fix. One regex per failure class."""

from __future__ import annotations

import re
import time

from shdpa.models import Action, Incident

RULES = [
    (r"UndefinedColumn|column \".*?\" does not exist", "schema_drift", "code_patch"),
    (r"MemoryError|exit code 137", "oom", "config_change"),
    (r"5\d\d\b|ConnectionError|HTTPError", "upstream_5xx", "retry"),
    (r"ModuleNotFoundError|No module named", "dep_conflict", "config_change"),
    (r"duplicate key|UniqueViolation", "idempotency", "code_patch"),
    (r"RefreshError|401|403", "auth_expiry", "secret_rotate"),
    (r"No space left|XCom value exceeds", "disk_full", "config_change"),
    (r"DagBag import errors|NameError.*datetime", "dag_import", "code_patch"),
    (r"not_null|TestFailure", "null_spike", "code_patch"),
    (r"sensor.*timeout", "late_partition", "config_change"),
]


def run(incident: Incident) -> Incident:
    t0 = time.time()
    log = (incident.log_text or "") + " " + (incident.exception_message or "")
    cls = "unknown"
    fix_kind = "noop"
    for pat, c, f in RULES:
        if re.search(pat, log, re.IGNORECASE):
            cls, fix_kind = c, f
            break

    incident.predicted_class = cls
    incident.predicted_class_confidence = 0.7 if cls != "unknown" else 0.0
    incident.proposed_fix_kind = fix_kind

    # crude templated patch for schema_drift: try to copy must_include_strings from rename
    if cls == "schema_drift":
        # naive: just produce a diff containing the column from exception_message
        m = re.search(r'column "([^"]+)" does not exist', log, re.IGNORECASE)
        if m:
            col = m.group(1)
            incident.proposed_fix_diff = f"- {col}\n+ <renamed>\n"
            incident.proposed_files_changed = ["models/<unknown>.sql"]

    action_kind = (
        "pr"
        if fix_kind in ("code_patch", "config_change", "secret_rotate")
        else ("retry" if fix_kind == "retry" else "noop")
    )
    incident.actions.append(Action(kind=action_kind, payload={"policy": "B1"}, dry_run=True))
    incident.resolved = False  # B1 is too dumb to actually match the must_include_strings
    incident.resolution_kind = "unresolved"
    incident.total_latency_s = time.time() - t0
    return incident
