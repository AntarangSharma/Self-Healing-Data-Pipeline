import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest

from shdpa.agent.guardrails import Guardrails, GuardrailViolation
from shdpa.models import Action, Incident
from shdpa.storage.sqlite_store import SQLiteStore


def test_refactor_cap_sqlite(tmp_path):
    db_path = tmp_path / "test.db"
    store = SQLiteStore(db_path)

    # Mock get_default_store to return our test store
    with patch("shdpa.storage.get_default_store", return_value=store), \
         patch.dict(os.environ, {"SHDPA_STORAGE_PATH": str(db_path)}):

        g = Guardrails()
        a = Action(kind="pr")

        # 1st attempt: 0 history. Should pass.
        g.check_action(a, predicted_class="schema_drift", confidence=0.9, diff="", files_changed=["my_model.sql"])

        # Save 1st incident to database
        inc1 = Incident(
            dag_id="d1", task_id="t1",
            proposed_files_changed=["my_model.sql"],
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10)
        )
        store.save_incident(inc1)

        # 2nd attempt: 1 history. Should pass.
        g.check_action(a, predicted_class="schema_drift", confidence=0.9, diff="", files_changed=["my_model.sql"])

        # Save 2nd incident to database
        inc2 = Incident(
            dag_id="d1", task_id="t2",
            proposed_files_changed=["my_model.sql"],
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        store.save_incident(inc2)

        # 3rd attempt: 2 history. Should raise GuardrailViolation with "refactor_cap_exceeded"
        with pytest.raises(GuardrailViolation) as excinfo:
            g.check_action(a, predicted_class="schema_drift", confidence=0.9, diff="", files_changed=["my_model.sql"])

        assert "refactor_cap_exceeded" in str(excinfo.value)

        # Check that different file has 0 history and passes
        g.check_action(a, predicted_class="schema_drift", confidence=0.9, diff="", files_changed=["other_model.sql"])
