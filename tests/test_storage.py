"""Tests for the SQLite incident store + audit-log integrity."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shdpa.models import Action, Incident, LLMCall
from shdpa.storage import SQLiteStore, get_default_store


def _make_incident(**over) -> Incident:
    base = dict(
        dag_id="dag_a", task_id="task_b",
        predicted_class="schema_drift",
        predicted_class_confidence=0.9,
        resolved=True, resolution_kind="auto",
        total_cost_usd=0.01, total_latency_s=1.5,
        log_text="hello",
    )
    base.update(over)
    inc = Incident(**base)
    inc.llm_calls.append(LLMCall(
        model="m", provider="mock", prompt_tokens=10,
        completion_tokens=5, cost_usd=0.005, latency_ms=12, purpose="triage",
    ))
    inc.actions.append(Action(kind="pr", payload={"url": "http://x"}, dry_run=False))
    return inc


def test_roundtrip(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.db")
    inc = _make_incident()
    iid = store.save_incident(inc)
    got = store.get_incident(iid)
    assert got is not None
    assert got.id == inc.id
    assert got.predicted_class == "schema_drift"
    assert got.actions[0].payload["url"] == "http://x"


def test_list_filters(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.db")
    store.save_incident(_make_incident(predicted_class="oom", resolved=False))
    store.save_incident(_make_incident(predicted_class="schema_drift"))
    store.save_incident(_make_incident(predicted_class="schema_drift"))
    drift = store.list_incidents(predicted_class="schema_drift")
    assert len(drift) == 2
    all_ = store.list_incidents()
    assert len(all_) == 3


def test_aggregate(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.db")
    store.save_incident(_make_incident(resolved=True, total_cost_usd=0.01))
    store.save_incident(_make_incident(resolved=True, total_cost_usd=0.02))
    store.save_incident(_make_incident(resolved=False, total_cost_usd=0.03))
    agg = store.aggregate()
    assert agg["n"] == 3
    assert agg["resolved"] == 2
    assert abs(agg["resolution_rate"] - 2/3) < 1e-9
    assert abs(agg["total_cost_usd"] - 0.06) < 1e-9


def test_audit_clean(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.db")
    store.save_incident(_make_incident())
    store.save_incident(_make_incident())
    assert store.verify_audit() == []


def test_audit_detects_tampering(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    store = SQLiteStore(db)
    inc = _make_incident()
    iid = store.save_incident(inc)
    # tamper: rewrite raw_json directly bypassing save_incident
    tampered = json.loads(inc.model_dump_json())
    tampered["predicted_class"] = "oom"
    store._conn.execute(  # noqa: SLF001 — test deliberately bypasses API
        "UPDATE incidents SET predicted_class=?, raw_json=? WHERE id=?",
        ("oom", json.dumps(tampered), iid),
    )
    store._conn.commit()
    bad = store.verify_audit()
    assert len(bad) == 1
    assert bad[0]["incident_id"] == iid
    assert bad[0]["expected_sha"] != bad[0]["actual_sha"]


def test_get_default_store_env_gated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SHDPA_STORAGE_PATH", raising=False)
    # reset module-level singleton
    import shdpa.storage.sqlite_store as ss
    ss._default_store = None
    assert get_default_store() is None
    monkeypatch.setenv("SHDPA_STORAGE_PATH", str(tmp_path / "live.db"))
    s = get_default_store()
    assert s is not None
    assert s.aggregate()["n"] == 0
