"""Translate dbt failures → shdpa Incidents.

Usage:
  # in dbt_project.yml on-run-end:
  #   "{{ shdpa_on_run_end() }}"
  # then in CI / Airflow:
  dbt test || python -m shdpa_dbt_callback path/to/dbt-project

This reads `<project>/target/run_results.json` (always written by dbt 1.6+),
finds failed/errored nodes, and POSTs an Incident per failure to the agent.

Why a separate script instead of "have the macro call the agent": dbt
macros run inside the warehouse adapter. No outbound HTTP, no Python
network stack. The macro writes a marker; this Python tool is the bridge.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def _post(url: str, body: dict[str, Any]) -> bool:
    try:
        req = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[shdpa-dbt] POST failed: {e!r}\n")
        return False


def _to_incident(node: dict[str, Any], project_path: Path) -> dict[str, Any]:
    return {
        "source": "manual",            # Incident.source Literal: airflow_callback|manual|replay|chaos
        "dag_id": f"dbt:{project_path.name}",
        "task_id": node["unique_id"],
        "run_id": "",
        "repo_path": str(project_path),
        "log_text": (
            f"dbt {node['status']}: {node.get('message', '')}\n"
            f"--- compiled SQL ---\n{node.get('compiled_code', '')}"
        ),
        "exception_type": "DbtTestFailure" if node["status"] == "fail" else "DbtNodeError",
        "exception_message": node.get("message", "") or "(no message)",
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: shdpa_dbt_callback <dbt-project-dir>", file=sys.stderr)
        return 2
    project = Path(argv[1])
    rr = project / "target" / "run_results.json"
    if not rr.exists():
        print(f"no {rr} — did dbt run?", file=sys.stderr)
        return 0  # nothing to do is not an error
    url = os.getenv("SHDPA_CALLBACK_URL", "http://localhost:8080/incidents")
    data = json.loads(rr.read_text())
    n = 0
    for r in data.get("results", []):
        if r.get("status") in ("fail", "error"):
            inc = _to_incident(r, project)
            if _post(url, inc):
                n += 1
                print(f"[shdpa-dbt] posted {r['unique_id']} ({r['status']})")
    print(f"[shdpa-dbt] {n} incident(s) sent")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
