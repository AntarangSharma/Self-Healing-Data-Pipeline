# Self-Healing Data Pipeline Agent — Initial Plan (v1)

> Author: Antarang Sharma
> Date: 2026-05-21
> Status: v1 (superseded by v2 — see `01_revised_plan.md`)

## Scope adjustments made before producing the plan

- **Narrow the orchestrator to Airflow only.** Supporting both Airflow + Dagster doubles the surface area on log parsers, hooks, and DAG introspection. Pick Airflow (more hireable, more public failure data). Mention Dagster as "future work" in the README.
- **Make the "PR with writeup" the default; auto-remediation is the rare path.** Recruiters distrust unsupervised auto-fixes. Framing the agent as a "Diagnose + draft fix" copilot that *can* auto-execute a whitelisted subset is more credible and shows judgment. Hero metric becomes "MTTR reduction" + "% of incidents with correct root cause in PR" rather than "% auto-resolved."
- **Replace "real historical failures" with a chaos-injected benchmark you fully control.** Mining real GitHub issues for ground-truth fixes is brittle and you'll spend week 3 doing data labeling instead of engineering. Generate failures deterministically; that *is* the eval contribution.

---

# DELIVERABLE 1 — ARCHITECTURE

## Component diagram (text)

```
                         ┌────────────────────────────┐
                         │  Airflow 2.9 (LocalExecutor)│
                         │  DAGs: TPC-H + NYC taxi ELT │
                         └──────────────┬─────────────┘
                                        │ task_instance events
                                        │ (StatsD → OTel collector)
                                        ▼
┌──────────────────────┐        ┌───────────────────────┐
│ Fault Injector       │──────▶ │ Event Router (FastAPI)│
│ (chaos scripts +     │        │  /airflow/callback    │
│  Airflow on_failure) │        └──────────┬────────────┘
└──────────────────────┘                   │ publishes Incident
                                           ▼
                                ┌─────────────────────────┐
                                │  Redis Streams (bus)    │
                                │  stream: incidents.raw  │
                                └──────────┬──────────────┘
                                           ▼
                  ┌────────────────────────────────────────────┐
                  │  Agent Worker (LangGraph state machine)    │
                  │  nodes: Triage → Diagnose → Plan →         │
                  │         Verify → Act → Report              │
                  └──┬─────────────┬──────────────┬───────────┘
                     │ tool calls  │              │
                     ▼             ▼              ▼
        ┌───────────────┐  ┌──────────────┐  ┌──────────────────┐
        │ Tool: Logs    │  │ Tool: Git    │  │ Tool: Sandbox    │
        │ (Loki API)    │  │ (GitPython + │  │ (ephemeral docker│
        │               │  │  GitHub API) │  │  + dbt compile)  │
        └───────────────┘  └──────────────┘  └──────────────────┘
        ┌───────────────┐  ┌──────────────┐  ┌──────────────────┐
        │ Tool: Schema  │  │ Tool: PR     │  │ Tool: Slack/Page │
        │ (Postgres     │  │ (gh CLI)     │  │ (webhook)        │
        │  info_schema) │  │              │  │                  │
        └───────────────┘  └──────────────┘  └──────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │ Postgres (state store)     │
        │ tables: incidents, actions,│
        │  evals, runs               │
        └────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │ Eval Harness (pytest +     │
        │  custom replay runner)     │
        │ → results.parquet → dash   │
        └────────────────────────────┘

Observability sidecar: OpenTelemetry → Grafana Tempo/Loki/Prom (docker-compose)
```

## Stack choices & justification

| Layer | Choice | Why |
|---|---|---|
| Orchestrator | **Airflow 2.9 LocalExecutor** | Industry default; richest public failure corpus; `on_failure_callback` hook is well-documented. |
| Message bus | **Redis Streams 7** | One container, durable, consumer groups, no Kafka ops tax for a portfolio repo. |
| Agent framework | **LangGraph 0.2** (with plain OpenAI/Anthropic function calling under the hood) | Explicit state machine = inspectable in interviews; not a black-box ReAct loop. |
| LLM provider/model | **Anthropic `claude-sonnet-4` for diagnosis**, **`claude-haiku-4` for triage/classification** | Cost split: cheap classifier gates the expensive reasoner. [ASSUMPTION] you have API budget ~$30 for the benchmark. |
| Vector store | **pgvector on the same Postgres** | Avoid a second datastore. Used only for retrieving similar past incidents (k=5). |
| Sandbox | **Docker-in-docker w/ resource caps + read-only mounts** | For `dbt compile`, `dbt run --target sandbox`, and replaying a single task against a snapshot DB. |
| Eval harness | **pytest + custom `replay.py` runner**, results to Parquet, surfaced in a Streamlit page | Reproducible, CI-runnable. |
| Observability | **OpenTelemetry → Grafana stack (Loki, Tempo, Prometheus) via docker-compose** | One `docker compose up`, gives you "look I shipped traces" screenshots. |
| IaC | **Terraform for Fly.io + docker-compose for local** | Terraform on resume; docker-compose for the 3-command quickstart. |
| Deployment target | **Fly.io (agent + Postgres + Redis) + GitHub Actions for the eval CI** | Cheap, fast cold start, public URL for the demo. |
| Code quality | **uv, ruff, mypy --strict, pytest, pre-commit** | Signals production hygiene. |

## Failure-class taxonomy (10 classes)

| # | Class | Detection signal | Diagnosis approach | Remediation policy |
|---|---|---|---|---|
| 1 | **Schema drift** (added/removed/retyped column upstream) | `dbt test` column-exists failure OR `psycopg.errors.UndefinedColumn` in task log | Diff `information_schema.columns` between last green run snapshot and now; ask LLM to map old→new | **Auto-fix** if rename only & dbt model has `{{ ref }}` lineage: open PR updating model; **PR-only** if type change |
| 2 | **Null spike / data quality** | `dbt test not_null` fail OR Great Expectations check fail | Profile column null-rate over last N runs; LLM hypothesizes upstream cause | **PR** adding a temporary `where col is not null` filter + GH issue tagging owner; **never auto-merge** |
| 3 | **Upstream API 5xx / timeout** | HTTP status in log; `requests.exceptions.*` | Check if transient (last 15 min error rate) via Loki query | **Auto-fix**: retry with exponential backoff up to N; if still failing, page |
| 4 | **OOM / worker killed** | Exit code 137; `MemoryError` | Look at task's recent input row counts; compare to historical p95 | **PR** bumping `executor_config` memory or switching to chunked read; never auto-bump in prod |
| 5 | **Late-arriving partition** | Sensor timeout; partition row count = 0 | Query source for max(event_time); compare to expected SLA | **Auto-fix**: extend sensor `timeout` once, then page on second occurrence |
| 6 | **Auth / token expiry** | 401/403; `google.auth.exceptions.RefreshError` | Check secret age in secret manager | **Page human** (never auto-rotate secrets) + draft runbook comment |
| 7 | **DAG import error** | Scheduler logs `DagBag import errors` | `git log -p` on the DAG file since last green parse; run `python -c "import dag"` in sandbox | **Auto-fix** if it's a known-safe import (e.g. `from datetime import datetime` missing) → PR; otherwise PR with stack trace |
| 8 | **Dependency conflict** | `ModuleNotFoundError`; pip resolver error in task log | Diff `requirements.txt` / `uv.lock` since last green; check PyPI for yanked versions | **PR** pinning to last-known-good version |
| 9 | **Idempotency violation** (duplicate primary key) | `IntegrityError: duplicate key` | Check if upstream produced overlapping windows | **PR** adding `ON CONFLICT DO UPDATE` or `MERGE`; never auto-truncate |
| 10 | **Disk full / spill** | `OSError: No space left`; Airflow XCom size limits | Disk usage from node-exporter; XCom table size | **Auto-fix**: prune Airflow XCom + logs older than 7d (whitelisted); page on infra disk |

## Agent loop (LangGraph state machine)

States: `triage → diagnose → plan → verify → act → report` with conditional edge back from `verify` to `diagnose` (max 2 loops).

**Tools the agent can call:**
- `get_task_logs(dag_id, task_id, run_id, tail=500)` — Loki API
- `get_recent_diff(file_path, since="last_green_run")` — GitPython
- `get_schema(table)` / `diff_schema(table, t1, t2)` — Postgres
- `run_dbt_compile(model)` and `run_dbt_test(model)` — subprocess in sandbox
- `replay_task_in_sandbox(dag_id, task_id, run_id)` — spins ephemeral container against a snapshot DB
- `search_similar_incidents(embedding, k=5)` — pgvector
- `open_pr(branch, title, body, files)` — `gh` CLI
- `post_slack(channel, blocks)` — webhook
- `page_oncall(severity)` — PagerDuty stub (no-op in demo)

**Guardrails (this is the interview gold):**
1. **Blast-radius cap**: tool registry has `max_files_touched=3`, `max_lines_changed=80`, `forbidden_paths=["**/prod_*.yml", "infra/**"]`.
2. **Dry-run default**: every `act` runs in sandbox first; diff is attached to PR.
3. **Two-key rule for destructive ops**: dropping/truncating/`DELETE` requires `--i-know-what-im-doing` env flag + human PR approval.
4. **Action budget**: ≤ $0.50 LLM spend per incident, ≤ 6 tool calls; circuit-breaks to "PR with logs" if exceeded.
5. **Rollback**: every auto-action records inverse action in `actions` table (e.g., previous DAG file SHA); single CLI `agent rollback <action_id>`.
6. **Confidence gate**: agent must emit `confidence ∈ [0,1]`; auto-act only if ≥ 0.85 *and* class is in auto-fix whitelist.
7. **Audit log**: every tool call, prompt, and response written to `actions` table with immutable hash chain.

## Incident data model (Pydantic v2)

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID, uuid4

FailureClass = Literal[
    "schema_drift", "null_spike", "upstream_5xx", "oom",
    "late_partition", "auth_expiry", "dag_import",
    "dep_conflict", "idempotency", "disk_full", "unknown",
]

class ToolCall(BaseModel):
    name: str
    args: dict
    result_summary: str  # truncated to 2KB
    latency_ms: int
    cost_usd: float = 0.0

class Action(BaseModel):
    kind: Literal["pr", "retry", "slack", "page", "noop"]
    payload: dict             # e.g. {"pr_url": "...", "branch": "..."}
    inverse: Optional[dict]   # for rollback
    executed_at: Optional[datetime]
    dry_run: bool = True

class Incident(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime
    source: Literal["airflow_callback", "manual", "replay"]
    dag_id: str
    task_id: str
    run_id: str
    raw_log_uri: str          # s3://... or file://
    exception_type: Optional[str]
    exception_message: Optional[str]
    predicted_class: Optional[FailureClass] = None
    predicted_class_confidence: float = 0.0
    root_cause_summary: Optional[str] = None  # ≤ 280 chars
    tool_calls: list[ToolCall] = []
    actions: list[Action] = []
    resolved: bool = False
    resolution_kind: Optional[Literal["auto", "pr", "human", "unresolved"]] = None
    total_cost_usd: float = 0.0
    total_latency_s: float = 0.0
    # eval-only fields
    ground_truth_class: Optional[FailureClass] = None
    ground_truth_fix_sha: Optional[str] = None
```

## Cost model (1,000 incidents/month)

[ASSUMPTION] Anthropic pricing: Haiku 4 ≈ $1/MTok in, $5/MTok out; Sonnet 4 ≈ $3/MTok in, $15/MTok out.

| Component | Per-incident | Notes |
|---|---|---|
| Triage (Haiku, ~2k in / 200 out) | $0.003 | classifies failure class |
| Diagnose (Sonnet, ~8k in / 1k out, ~70% of incidents) | $0.039 avg | only invoked if triage confidence < 0.95 |
| Tool calls (logs, git, sandbox) — infra | $0.005 | Fly.io worker share |
| Storage (logs + embeddings) | $0.001 | pgvector row + 4KB log |
| **Total per incident** | **~$0.048** | |
| **Monthly @ 1k** | **~$48** | |

---

# DELIVERABLE 2 — EVAL DATASET & METHODOLOGY

## Constructing 200 labeled incidents without real production data

Target: **200 incidents**, split **140 train / 60 held-out test**. Sources:

1. **Chaos injection into a seeded warehouse (60% — 120 incidents).** Stand up Postgres with TPC-H (scale 1) + NYC taxi sample. Build 6 DAGs (ingest → stage → mart). Write `chaos/inject.py` with deterministic seeds:
   - `inject.schema_drop_column(table, col)`
   - `inject.schema_rename_column(table, old, new)`
   - `inject.schema_retype(table, col, new_type)`
   - `inject.null_spike(table, col, pct)`
   - `inject.api_5xx(endpoint, duration_s)` (toxiproxy in front of a mock API)
   - `inject.oom(task, mem_limit_mb=128)` (Airflow `executor_config`)
   - `inject.dag_syntax_error(dag_file)` (insert a bad line via patch)
   - `inject.dep_conflict(requirements, pkg, bad_version)`
   - `inject.duplicate_rows(table, n)`
   - `inject.disk_fill(path, mb)` (truncate-fill a tmpfs)
   - `inject.late_partition(table, hours_late)`
   - `inject.auth_expire(secret_name)`

2. **Public-issue mining (25% — 50 incidents).** Scrape `apache/airflow` and `dbt-labs/dbt-core` GitHub issues with labels `bug`, `kind:bug`. Filter to issues with a stack trace + a linked fix PR. Manually label root cause class. **8 hour budget.**

3. **Stack Overflow trace harvesting (15% — 30 incidents).** Search SO for `[airflow] error:` with accepted answers. License: SO answers are CC BY-SA — credit the URL in the fixture metadata.

## Labeled fixture schema (per incident, on disk as `fixture.yaml`)

```yaml
id: f4a1...
source: chaos | github | stackoverflow
inputs:
  log_path: log.txt              # the raw task log the agent sees
  repo_snapshot: repo.tar.gz     # repo state at time of failure
  schema_snapshot: schema.json   # information_schema dump
  dag_id: tpch_stage
  task_id: load_orders
  run_id: scheduled__2025-...
ground_truth:
  class: schema_drift
  root_cause_summary: "column orders.o_priority renamed to orders.priority upstream"
  fix:
    kind: code_patch              # or: retry | config_change | secret_rotate | noop
    diff_path: fix.patch          # unified diff against repo_snapshot
    files_changed: ["models/stg_orders.sql"]
  severity: P2                    # P1..P4
  auto_fixable: true              # is this class in the auto-fix whitelist?
  expected_actions:
    - kind: pr
      must_include_strings: ["o_priority", "priority"]
provenance:
  url: null                       # SO/GH URL if applicable
  chaos_seed: 42
  injected_by: inject.schema_rename_column
license: cc-by-sa | mit | internal
```

## Metrics

| Metric | Definition | How computed |
|---|---|---|
| **Resolution Rate** | % incidents where `predicted_fix` matches ground truth (semantically) | For `code_patch`: diff overlap ≥ 0.7 (line-level Jaccard) **AND** `must_include_strings` all present. For `retry`/`noop`: exact match. |
| **Root-Cause Classification Accuracy** | top-1 class accuracy on 10 classes | Confusion matrix, macro F1 reported too |
| **MTTR (Mean Time To Remediate)** | seconds from incident ingestion to PR opened / action executed | Wall clock in eval harness |
| **Guardrail Catch Rate** | % of attempted-unsafe-actions blocked | Inject 20 adversarial fixtures; measure block rate |
| **$ / incident** | Sum of LLM + infra cost ÷ N | Token counts from Anthropic API response × pricing |
| **Regression Rate** | % of held-out test incidents that pass in run N but fail in run N+1 | Compare results.parquet across commits in CI |
| **Coverage** | % of failure classes with ≥ 5 fixtures *and* ≥ 70% resolution | Per-class breakdown |
| **Hallucination Rate** | % of PRs that reference a file/column/symbol that does not exist in the repo snapshot | AST/grep check on the diff |

## Baselines (results table template — fill in week 6)

| Policy | Resolution Rate | Class Acc | MTTR (s) | Guardrail Catch | $/incident | Hallucination |
|---|---:|---:|---:|---:|---:|---:|
| B0: Restart-only | _ | n/a | _ | n/a | $0.00 | n/a |
| B1: Rules-only (regex → class → templated fix) | _ | _ | _ | _ | $0.00 | _ |
| B2: Single LLM call (Sonnet, logs pasted, no tools) | _ | _ | _ | _ | _ | _ |
| B3: Single LLM call + retrieval (k=5 past incidents) | _ | _ | _ | _ | _ | _ |
| **Ours: LangGraph agent + tools + guardrails** | **target ≥ 0.70** | **≥ 0.85** | **< 90** | **≥ 0.95** | **≤ $0.05** | **≤ 0.05** |

## Contamination prevention

1. **Hard split by source + by timestamp.** Held-out 60 fixtures are all generated *after* the agent's last prompt edit.
2. **Hash check.** Every fixture has `sha256(log + repo_snapshot)`; CI fails if any hash appears in the prompt history of the LLM.
3. **Strip identifying strings.** Fixture loader scrubs the fixture UUID and any `chaos_seed` from inputs before passing to agent.
4. **Memorization probe.** Periodically prompt the model with a known fixture log *without* tools and check if it volunteers the exact fix verbatim.
5. **No fine-tuning.** Stay zero-shot / few-shot via retrieval only.
6. **Public-issue fixtures**: include them in **train only**, never in held-out test.

---

# DELIVERABLE 3 — 6-WEEK BUILD PLAN

(Week-by-week details — see `01_revised_plan.md` for the updated version.)

- **Week 1** — End-to-end thin slice (one failure class, local Airflow + Postgres)
- **Week 2** — Failure-class breadth (6 of 10 classes, 60 fixtures)
- **Week 3** — Tools + sandbox + guardrails (20 adversarial fixtures)
- **Week 4** — Remaining classes + observability (200 fixtures total)
- **Week 5** — Baselines, prompt iteration, held-out evals
- **Week 6** — Deploy, write, ship (Fly.io, README, blog, LinkedIn)

---

# DELIVERABLE 4 — README + BLOG + LAUNCH

## README outline

```
# Self-Healing Data Pipeline Agent

> Resolves 72% of common Airflow failures with a PR + root-cause writeup,
> on a benchmark of 200 chaos-injected incidents. Avg cost: $0.04/incident.
> Avg time-to-PR: 78s.

[ HERO GIF: failed task → red dot → PR opens → green dot, ~12s real time ]

## Why this exists
## What it does in 60 seconds
## Architecture
## Benchmark results
## Run it yourself in 3 commands
## Failure classes covered
## Guardrails (what it WON'T do)
## Limitations & honest caveats
## What I'd do with another month
## Tech stack
## Contact
```

## Blog post candidate titles (best first)

1. **"I gave an LLM agent root on my Airflow — here's the 200-incident benchmark"**
2. "Self-healing data pipelines: what works, what doesn't, and the metric nobody reports"
3. "Why your on-call shouldn't be a regex: building a pipeline agent that earned its merge rights"

## LinkedIn launch post (≤280 chars)

> I spent 6 weeks building an agent that diagnoses Airflow failures, opens a PR with the fix, and proves it works.
>
> On a 200-incident benchmark: 72% resolved, 78s avg time-to-PR, $0.04 each. Beats a single-LLM-call baseline by 28 points.
>
> Repo + blog + benchmark: <link>

## Three STAR interview stories

1. **End-to-end ownership** — scoped, built, measured, shipped in 6 weeks.
2. **Avoided over-engineering** — cut Dagster, Kafka, Pinecone, fine-tuning.
3. **Designed for safety** — 6-layer guardrails + 20 adversarial fixtures + zero unsafe actions on held-out.
