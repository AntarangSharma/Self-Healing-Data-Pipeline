"""Example DAG that fails on purpose so you can see the agent end-to-end.

After `docker compose up`:
  1. Open http://localhost:8081 (Airflow UI; admin/admin)
  2. Enable `shdpa_example_failing`
  3. Trigger a run.
  4. Watch the agent receive the callback: `docker compose logs -f shdpa`
  5. Inspect the resulting incident: `curl http://localhost:8080/incidents | jq .`
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# When this file lives in $AIRFLOW_HOME/dags/, Airflow auto-imports plugins
# from $AIRFLOW_HOME/plugins/.
try:
    from shdpa_callback import shdpa_on_failure_callback
except ImportError:
    shdpa_on_failure_callback = None  # type: ignore[assignment]


def _boom() -> None:
    # Simulate a schema_drift failure — the agent should triage this correctly.
    raise KeyError(
        "column 'o_customerkey' not found in table 'orders' "
        "(did you mean 'o_custkey'?)"
    )


with DAG(
    dag_id="shdpa_example_failing",
    start_date=datetime(2025, 1, 1),
    schedule=None,
    catchup=False,
    default_args={
        "owner": "shdpa-demo",
        "retries": 0,
        "retry_delay": timedelta(minutes=1),
        # The line that wires it all up:
        "on_failure_callback": shdpa_on_failure_callback,
    },
    tags=["shdpa", "demo"],
) as dag:
    PythonOperator(task_id="will_fail", python_callable=_boom)
