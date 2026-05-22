"""Airflow `on_failure_callback` → shdpa agent.

Drop this file in `$AIRFLOW_HOME/plugins/` (or symlink), then in your DAG:

    from shdpa_callback import shdpa_on_failure_callback

    with DAG(..., default_args={"on_failure_callback": shdpa_on_failure_callback}):
        ...

The callback POSTs a structured Incident JSON to the agent's HTTP surface
(`POST /incidents`). It is INTENTIONALLY non-blocking — a 5s timeout, and any
network failure is swallowed with a stderr log line. The agent failing must
NEVER cause the task to fail differently than it already did.

Env vars consumed:
  SHDPA_CALLBACK_URL  - default http://shdpa:8080/incidents
  SHDPA_CALLBACK_TIMEOUT - default 5 (seconds)
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


def _safe_str(x: Any, n: int = 4000) -> str:
    try:
        s = str(x)
    except Exception:  # noqa: BLE001
        s = repr(x)
    return s[-n:]


def _tail_log(ti: Any, n_lines: int = 200) -> str:
    """Read the last N lines from the task instance log directory.

    Airflow's TaskInstance has `.log_filepath` on >=2.6. We fall back to
    `try_number` reconstruction for older versions.
    """
    try:
        # Modern Airflow exposes log_url / log_filepath; try to read directly.
        path = getattr(ti, "log_filepath", None)
        if not path:
            return _safe_str(getattr(ti, "log_url", ""))
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n_lines:])
    except Exception:  # noqa: BLE001
        return ""


def shdpa_on_failure_callback(context: dict[str, Any]) -> None:
    """Airflow callback signature. `context` is the dict Airflow passes in."""
    url = os.getenv("SHDPA_CALLBACK_URL", "http://shdpa:8080/incidents")
    timeout = float(os.getenv("SHDPA_CALLBACK_TIMEOUT", "5"))

    ti = context.get("task_instance") or context.get("ti")
    exc = context.get("exception")
    dag = context.get("dag")

    body = {
        "source": "airflow_callback",
        "dag_id": getattr(dag, "dag_id", "") or context.get("dag_id", ""),
        "task_id": getattr(ti, "task_id", "") or context.get("task_id", ""),
        "run_id": getattr(ti, "run_id", "") or context.get("run_id", ""),
        "exception_type": type(exc).__name__ if exc else None,
        "exception_message": _safe_str(exc, 1000) if exc else None,
        "log_text": _tail_log(ti),
        "repo_path": os.getenv("SHDPA_REPO_PATH", ""),
    }

    try:
        req = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "shdpa-airflow/0.1"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            sys.stderr.write(
                f"[shdpa] callback POST {url} -> {resp.status}\n"
            )
    except URLError as e:
        sys.stderr.write(f"[shdpa] callback failed (URLError): {e!r}\n")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(
            f"[shdpa] callback failed: {e!r}\n{traceback.format_exc()}\n"
        )
    # ALWAYS swallow — Airflow already considers the task failed; raising
    # here would mask the original exception.
