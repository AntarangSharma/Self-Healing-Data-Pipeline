"""End-to-end smoke test: chaos → fixture → agent → score, all on mock LLM."""
import shutil
import tempfile
from pathlib import Path

import pytest

from shdpa.agent.loop import run_agent
from shdpa.chaos import generate_fixture
from shdpa.eval.fixture import load_fixture
from shdpa.eval.metrics import score_incident


@pytest.mark.parametrize("kind", [
    "schema_rename_column",
    "upstream_5xx",
    "auth_expiry",
    "disk_full",
    "dep_conflict",
    "idempotency",
    "null_spike",
    "oom",
    "dag_import",
])
def test_mock_agent_resolves(kind: str):
    tmp = Path(tempfile.mkdtemp())
    try:
        out = tmp / kind
        generate_fixture(kind, out, seed=0)
        incident = load_fixture(out)
        incident = run_agent(incident)
        score = score_incident(incident)
        assert score.class_correct, f"{kind}: predicted {incident.predicted_class}"
        assert score.resolved, f"{kind}: did not resolve"
    finally:
        shutil.rmtree(tmp)
