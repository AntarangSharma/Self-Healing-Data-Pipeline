import json
import urllib.error
import urllib.request
from unittest import mock
import pytest

from shdpa.tools.registry import ToolResult, ToolRegistry
from shdpa.models import Incident
from shdpa.agent.loop import run_agent


class MockResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = body.encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def test_clear_airflow_task_success(monkeypatch):
    def mock_urlopen(req, timeout=None):
        assert req.method == "POST"
        assert "/dags/test_dag/clearTaskInstances" in req.full_url
        return MockResponse(200, json.dumps({"cleared": True}))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    from shdpa.tools.airflow_api import clear_airflow_task

    r = clear_airflow_task("test_dag", "test_task", "test_run")
    assert r.ok
    assert "cleared" in r.summary


def test_get_airflow_task_status_success(monkeypatch):
    def mock_urlopen(req, timeout=None):
        assert req.method == "GET"
        assert "/dags/test_dag/dagRuns/test_run/taskInstances/test_task" in req.full_url
        return MockResponse(200, json.dumps({"state": "success"}))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    from shdpa.tools.airflow_api import get_airflow_task_status

    r = get_airflow_task_status("test_dag", "test_task", "test_run")
    assert r.ok
    assert r.data["state"] == "success"


def test_agent_closed_loop_verify_success(monkeypatch):
    monkeypatch.setenv("SHDPA_LIVE_AIRFLOW_VERIFY", "1")

    incident = Incident(
        dag_id="test_dag",
        task_id="test_task",
        run_id="test_run",
        predicted_class="schema_drift",
        predicted_class_confidence=0.9,
    )

    # Mock loop functions and registry calls to avoid external services
    # We bypass LLM completion by mock diagnosing
    monkeypatch.setattr("shdpa.agent.loop._triage", lambda inc, llm, meter: None)

    def mock_diagnose(inc, llm, meter, registry, **kwargs):
        inc.predicted_class = "schema_drift"
        inc.predicted_class_confidence = 0.95
        return {
            "fix_kind": "code_patch",
            "root_cause": "column rename",
            "sql_replace": {"find": "col_a", "replace": "col_b"},
        }

    monkeypatch.setattr("shdpa.agent.loop._diagnose", mock_diagnose)

    # Mock make_pr to succeed
    from shdpa.models import Action

    monkeypatch.setattr(
        "shdpa.agent.loop._make_pr",
        lambda *args, **kwargs: Action(
            kind="pr", payload={"branch": "shdpa/fix-test", "url": "mock-url"}
        ),
    )

    # Mock registry tool calls
    original_call = ToolRegistry.call
    clear_called = False
    status_called_count = 0

    def mock_tool_call(self, name, incident, **kwargs):
        nonlocal clear_called, status_called_count
        if name == "clear_airflow_task":
            clear_called = True
            return ToolResult(ok=True, summary="Task cleared")
        elif name == "get_airflow_task_status":
            status_called_count += 1
            # Return running first, then success
            state = "running" if status_called_count == 1 else "success"
            return ToolResult(ok=True, summary=f"state: {state}", data={"state": state})
        return original_call(self, name, incident, **kwargs)

    monkeypatch.setattr(ToolRegistry, "call", mock_tool_call)

    # Run the agent
    out = run_agent(incident, dry_run=True)
    assert out.resolved
    assert out.resolution_kind == "auto"
    assert clear_called
    assert status_called_count == 2
    assert out.error is None


def test_agent_closed_loop_verify_failure(monkeypatch):
    monkeypatch.setenv("SHDPA_LIVE_AIRFLOW_VERIFY", "1")

    incident = Incident(
        dag_id="test_dag",
        task_id="test_task",
        run_id="test_run",
        predicted_class="schema_drift",
        predicted_class_confidence=0.9,
    )

    monkeypatch.setattr("shdpa.agent.loop._triage", lambda inc, llm, meter: None)

    def mock_diagnose(inc, llm, meter, registry, **kwargs):
        inc.predicted_class = "schema_drift"
        inc.predicted_class_confidence = 0.95
        return {
            "fix_kind": "code_patch",
            "root_cause": "column rename",
            "sql_replace": {"find": "col_a", "replace": "col_b"},
        }

    monkeypatch.setattr("shdpa.agent.loop._diagnose", mock_diagnose)

    from shdpa.models import Action

    monkeypatch.setattr(
        "shdpa.agent.loop._make_pr",
        lambda *args, **kwargs: Action(
            kind="pr", payload={"branch": "shdpa/fix-test", "url": "mock-url"}
        ),
    )

    original_call = ToolRegistry.call
    clear_called = False

    def mock_tool_call(self, name, incident, **kwargs):
        nonlocal clear_called
        if name == "clear_airflow_task":
            clear_called = True
            return ToolResult(ok=True, summary="Task cleared")
        elif name == "get_airflow_task_status":
            # Task repeatedly fails
            return ToolResult(ok=True, summary="state: failed", data={"state": "failed"})
        return original_call(self, name, incident, **kwargs)

    monkeypatch.setattr(ToolRegistry, "call", mock_tool_call)

    # Run the agent
    out = run_agent(incident, dry_run=True)
    assert not out.resolved
    assert out.resolution_kind == "unresolved"
    assert clear_called
    assert "live_verify_failed" in out.error
