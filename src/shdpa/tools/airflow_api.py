"""Airflow REST API client tools.

Provides endpoints to clear task instances (triggering retries) and check their status.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
import urllib.error
from typing import Any

from shdpa.tools.registry import Tool, ToolResult


def _airflow_request(endpoint: str, method: str = "GET", data: dict[str, Any] | None = None) -> tuple[int, dict[str, Any] | None, str | None]:
    api_url = os.getenv("AIRFLOW_API_URL", "http://localhost:8081/api/v1").rstrip("/")
    user = os.getenv("AIRFLOW_API_USER", "admin")
    password = os.getenv("AIRFLOW_API_PASSWORD", "admin")
    
    url = f"{api_url}/{endpoint.lstrip('/')}"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "shdpa-agent/0.1",
    }
    
    # Basic Authentication
    auth_str = f"{user}:{password}"
    b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    headers["Authorization"] = f"Basic {b64_auth}"
    
    req_data = None
    if data is not None:
        req_data = json.dumps(data).encode("utf-8")
        
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            resp_body = response.read().decode("utf-8")
            return response.status, json.loads(resp_body) if resp_body else {}, None
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_data = json.loads(err_body)
            err_msg = err_data.get("detail", str(e))
        except Exception:
            err_msg = str(e)
        return e.code, None, err_msg
    except Exception as e:
        return 0, None, str(e)


def clear_airflow_task(dag_id: str, task_id: str, run_id: str) -> ToolResult:
    """Clear a task instance in Airflow to trigger a retry."""
    payload = {
        "dry_run": False,
        "reset_dag_runs": True,
        "task_ids": [task_id],
        "dag_run_id": run_id,
    }
    status, res, err = _airflow_request(f"dags/{dag_id}/clearTaskInstances", method="POST", data=payload)
    if status == 200:
        return ToolResult(ok=True, summary=f"Task {dag_id}.{task_id} cleared successfully", data=res)
    return ToolResult(ok=False, summary=f"Failed to clear task: {err}", error=f"status_{status}")


def get_airflow_task_status(dag_id: str, task_id: str, run_id: str) -> ToolResult:
    """Retrieve the current state of a task instance."""
    status, res, err = _airflow_request(f"dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}")
    if status == 200 and res:
        state = res.get("state", "none")
        return ToolResult(ok=True, summary=f"Task state: {state}", data={"state": state})
    return ToolResult(ok=False, summary=f"Failed to get task state: {err}", error=f"status_{status}")


CLEAR_TASK_TOOL = Tool(
    name="clear_airflow_task",
    description="Clear a failed task instance in Airflow so it is retried.",
    schema={
        "type": "object",
        "properties": {
            "dag_id": {"type": "string"},
            "task_id": {"type": "string"},
            "run_id": {"type": "string"},
        },
        "required": ["dag_id", "task_id", "run_id"],
    },
    fn=clear_airflow_task,
)

GET_TASK_STATUS_TOOL = Tool(
    name="get_airflow_task_status",
    description="Get the execution state of an Airflow task instance.",
    schema={
        "type": "object",
        "properties": {
            "dag_id": {"type": "string"},
            "task_id": {"type": "string"},
            "run_id": {"type": "string"},
        },
        "required": ["dag_id", "task_id", "run_id"],
    },
    fn=get_airflow_task_status,
)
