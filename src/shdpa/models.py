"""Pydantic data model for incidents, tool calls, and actions.

This is the canonical schema. Every persisted record uses these types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

FailureClass = Literal[
    "schema_drift",
    "null_spike",
    "upstream_5xx",
    "oom",
    "late_partition",
    "auth_expiry",
    "dag_import",
    "dep_conflict",
    "idempotency",
    "disk_full",
    "unknown",
]

ResolutionKind = Literal["auto", "pr", "human", "unresolved"]
ActionKind = Literal["pr", "retry", "slack", "page", "noop"]
FixKind = Literal["code_patch", "retry", "config_change", "secret_rotate", "noop"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    error: str | None = None


class LLMCall(BaseModel):
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    purpose: str = ""  # "triage" | "diagnose" | "plan"


class Action(BaseModel):
    kind: ActionKind
    payload: dict[str, Any] = Field(default_factory=dict)
    inverse: dict[str, Any] | None = None
    executed_at: datetime | None = None
    dry_run: bool = True
    blocked_by_guardrail: str | None = None


class GroundTruthFix(BaseModel):
    kind: FixKind
    diff: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    must_include_strings: list[str] = Field(default_factory=list)


class GroundTruth(BaseModel):
    failure_class: FailureClass
    root_cause_summary: str
    fix: GroundTruthFix
    severity: Literal["P1", "P2", "P3", "P4"] = "P3"
    auto_fixable: bool = False


class Incident(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=_utcnow)
    source: Literal["airflow_callback", "manual", "replay", "chaos"] = "replay"

    # context
    dag_id: str = ""
    task_id: str = ""
    run_id: str = ""
    repo_path: str = ""
    log_text: str = ""
    schema_before: dict[str, Any] = Field(default_factory=dict)
    schema_after: dict[str, Any] = Field(default_factory=dict)

    exception_type: str | None = None
    exception_message: str | None = None

    # agent outputs
    predicted_class: FailureClass | None = None
    predicted_class_confidence: float = 0.0
    root_cause_summary: str | None = None
    proposed_fix_kind: FixKind | None = None
    proposed_fix_diff: str | None = None
    proposed_files_changed: list[str] = Field(default_factory=list)

    # bookkeeping
    tool_calls: list[ToolCall] = Field(default_factory=list)
    llm_calls: list[LLMCall] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)

    resolved: bool = False
    resolution_kind: ResolutionKind | None = None
    total_cost_usd: float = 0.0
    total_latency_s: float = 0.0
    error: str | None = None

    # eval-only
    ground_truth: GroundTruth | None = None
    fixture_id: str | None = None
