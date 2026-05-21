# Self-Healing Data Pipeline Agent — Revised Plan (v2)

> Author: Antarang Sharma
> Date: 2026-05-21
> Status: **active** — this is the plan we build from.
> Supersedes: `00_initial_plan.md`

## What changed vs. v1, and why

| Change | Reason |
|---|---|
| **Eval harness ships in week 1, not week 4** | The benchmark IS the project. Build it before you build the thing it measures, so you can't fudge numbers and you're never blocked on "what to improve next." |
| **Plain function-calling in v1; LangGraph only if/when we need it** | A 6-state machine is 150 lines of Python. Adopting LangGraph day-one is resume-driven design and a liability in interviews ("why this framework?"). Migrate later with a *reason*. |
| **Sandbox = Postgres schema, not Docker-in-docker** | DinD on macOS / Fly.io is a 2-day rabbit hole that adds little. A throwaway schema + `dbt build --target sandbox` gives identical isolation for our needs. |
| **Cut public-issue mining from the core benchmark** | Contamination risk + labeling pain. Move to optional "wild" held-out set (30 examples, no statistical claim). |
| **Two-track weekly cadence (agent + eval ship together)** | v1's all-agent-then-all-eval pattern is high-risk. Each week ships a slice of both. |
| **Deploy = Modal + Streamlit Cloud + Loom, not Fly.io live stack** | A multi-container live demo is a maintenance liability. Recorded demo + cheap public dashboard is more durable. |
| **Hard cost budget: $30 dev, $0.05/incident eval** | Replaces hand-wavy cost model with a concrete `cost_meter.py` middleware (itself a portfolio artifact). |
| **One reference incident drives everything** | `o_priority → priority` schema rename in `stg_orders`. Demo, GIF, blog, Loom, interview all use this exact incident. Build it first, polish it last. |
| **Pre-mortem doc** | `docs/02_premortem.md` before week 1. Forces explicit risk register. |
| **Prompt versioning is a first-class artifact** | `prompts/v{N}/*.md` + `evals/prompt_history.csv` row per change. The "what surprised me" section writes itself. |

## v0 done-definition (be honest about it)

By end of week 5, the project ships if **all** of these are true:
- [ ] ≥ 60% resolution rate on held-out 60 fixtures (target 70, accept 60)
- [ ] Beats all 3 baselines on at least 2 metrics
- [ ] Guardrail catch rate ≥ 95% on adversarial fixtures
- [ ] 3-command quickstart works on a fresh machine (tested in CI)
- [ ] Reference-incident demo runs end-to-end in < 90 seconds
- [ ] Loom + GIF + blog draft + LinkedIn post all in repo

If we're below 60% by end of week 5: **don't fake it.** The post becomes "Self-healing data pipelines: where LLM agents actually fall short" — which is *more* readable and more credible.

---

# DELIVERABLE 1 — ARCHITECTURE (v2)

## Component diagram (text)

```
                       ┌──────────────────────────────┐
                       │  Airflow 2.9 (LocalExecutor) │
                       │  DAGs: tpch_stg, tpch_mart   │
                       └──────────────┬───────────────┘
                                      │ on_failure_callback
                                      ▼
┌──────────────────┐         ┌──────────────────────────┐
│ Chaos Injector   │────────▶│ Event Router (FastAPI)   │
│ chaos/inject.py  │         │ POST /incidents          │
│ (deterministic   │         └──────────────┬───────────┘
│  seeds)          │                        │
└──────────────────┘                        ▼
                                  ┌────────────────────────┐
                                  │ Postgres 16            │
                                  │  - incidents           │
                                  │  - actions             │
                                  │  - runs                │
                                  │  - fixtures (meta)     │
                                  │  - prompt_history      │
                                  │  - embeddings (pgvec)  │
                                  └─────────┬──────────────┘
                                            ▼
                       ┌────────────────────────────────────┐
                       │ Agent Worker (Python, plain        │
                       │ function-calling loop)             │
                       │ States:                            │
                       │  triage → diagnose → plan          │
                       │       → verify → act → report      │
                       └─┬─────────┬─────────┬─────────────┘
                         │         │         │
                ┌────────▼──┐ ┌────▼──────┐ ┌▼──────────────┐
                │ ToolBox   │ │ Guardrail │ │ CostMeter     │
                │ (registry │ │ Middleware│ │ middleware    │
                │  + JSON   │ │ (radius,  │ │ (per-incident │
                │  schemas) │ │  budget,  │ │  budget, hard │
                │           │ │  forbids) │ │  stop)        │
                └────────┬──┘ └───────────┘ └───────────────┘
                         │
        ┌────────────────┼──────────────────┐
        ▼                ▼                  ▼
  ┌──────────┐    ┌──────────────┐   ┌──────────────────┐
  │ logs.py  │    │ git_diff.py  │   │ schema_diff.py   │
  │ (read    │    │ (GitPython,  │   │ (psycopg,        │
  │  task    │    │  last_green) │   │  info_schema     │
  │  log     │    │              │   │  snapshot diff)  │
  │  files)  │    └──────────────┘   └──────────────────┘
  └──────────┘
  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐
  │ sandbox.py       │  │ pr.py            │  │ retrieval.py │
  │ (CREATE SCHEMA   │  │ (gh CLI →        │  │ (pgvector    │
  │  sandbox_<id>;   │  │  draft PR on     │  │  k=5 similar │
  │  dbt build       │  │  local bare      │  │  incidents)  │
  │  --target=sbx)   │  │  repo or GH)     │  │              │
  └──────────────────┘  └──────────────────┘  └──────────────┘

                                  │
                                  ▼
                       ┌────────────────────────────┐
                       │ Eval Harness               │
                       │  replay.py                 │
                       │  metrics.py                │
                       │  baselines/{b0,b1,b2,b3}.py│
                       │  → results.parquet         │
                       └─────────┬──────────────────┘
                                 ▼
                       ┌────────────────────────────┐
                       │ Streamlit dashboard        │
                       │  (results, per-class       │
                       │   breakdown, confusion mx, │
                       │   prompt history)          │
                       └────────────────────────────┘

Observability: structlog → stdout (JSON) + OTel SDK → local Tempo (dev only).
               Skip Loki/Prom for v0 — overkill.
Deploy:        Modal Labs (agent worker) + Streamlit Cloud (dashboard) +
               GitHub Actions (eval CI on every PR).
```

## Stack choices (v2 — pared down)

| Layer | v2 choice | Why changed from v1 |
|---|---|---|
| Orchestrator | Airflow 2.9 LocalExecutor | unchanged |
| Message bus | **dropped** — direct DB write | Redis was overkill; FastAPI writes incidents to Postgres directly. |
| Agent framework | **Plain Python function-calling loop** | Defensible in interviews; LangGraph migration deferred to "if needed." |
| LLM provider | **Anthropic Claude (haiku-3.5 for triage, sonnet-3.5 or 4 for diagnosis)** OR **OpenAI gpt-4o-mini + gpt-4o** — decide week 1 by running both on 20 fixtures and picking by $/accuracy | Concrete bake-off instead of guessing. |
| Vector store | pgvector on same Postgres | unchanged |
| Sandbox | **Postgres schema (`sandbox_<incident_id>`)** + `dbt build --target sandbox` | No DinD pain. |
| Eval harness | pytest + custom `replay.py` + Parquet results + Streamlit dashboard | unchanged |
| Observability | structlog (JSON) + OTel SDK; **skip Grafana stack for v0** | Reduce moving parts. Mention Grafana as "see `docs/observability_roadmap.md`." |
| IaC | **docker-compose only** for local; **no Terraform** for v0 | Terraform on a portfolio repo with no real cloud spend is theater. |
| Deploy target | **Modal Labs (agent) + Streamlit Cloud (dashboard) + Loom (demo)** | Live multi-container Fly.io stack is fragile maintenance. |
| Code quality | uv, ruff, mypy --strict, pytest, pre-commit | unchanged |
| CI | GitHub Actions: lint, type, test, **run replay.py on 20-fixture smoke set on every PR** | Eval-gated CI is the differentiator. |

## Failure-class taxonomy (10 classes — unchanged from v1, but auto-fix list narrower)

| # | Class | Auto-fix in v0? |
|---|---|---|
| 1 | schema_drift (rename only) | ✅ PR auto-opened, never auto-merged |
| 2 | null_spike | ❌ PR only |
| 3 | upstream_5xx | ✅ retry up to 3× |
| 4 | oom | ❌ PR only |
| 5 | late_partition | ✅ extend sensor timeout once |
| 6 | auth_expiry | ❌ page only |
| 7 | dag_import (whitelisted patterns) | ✅ PR auto-opened |
| 8 | dep_conflict | ❌ PR only |
| 9 | idempotency | ❌ PR only |
| 10 | disk_full (XCom only) | ✅ prune XCom > 7d |

**v0 honest scope: 4 of 10 classes are auto-fixable.** The other 6 are PR-only. The README will say this *prominently* — recruiters will read it as judgment, not as a weakness.

## Agent loop — plain Python (v0)

```python
# pseudocode — ~150 LOC reality
def handle_incident(incident: Incident) -> Incident:
    incident = triage(incident)           # 1 LLM call (cheap model)
    if incident.predicted_class_confidence < 0.6:
        incident = diagnose(incident)     # tool-calling loop, expensive model
    plan = make_plan(incident)            # LLM call → structured Action[]
    plan = guardrails.filter(plan)        # drops actions exceeding budget/radius
    verified = sandbox.verify(plan)       # dry-run, capture diff
    if verified.ok and incident.confidence >= 0.85:
        execute(verified.actions)
    else:
        open_pr_with_writeup(incident, verified)
    return incident
```

Migration trigger to LangGraph: when we need (a) durable state between tool calls (resume after crash) or (b) parallel tool branches. Not before.

## Guardrails (unchanged from v1, but **enforced by middleware, not by prompt**)

The model is *told* about guardrails in the prompt **and** every tool call goes through a middleware that:
1. Rejects calls touching `forbidden_paths`
2. Counts files-touched and lines-changed; rejects if exceeded
3. Tracks $/incident cost; circuit-breaks if exceeded
4. Requires `confidence ≥ 0.85` AND `class ∈ auto_fix_whitelist` for any non-PR action
5. Writes inverse action for rollback BEFORE executing
6. Hash-chains the audit log

**This is the interview gold.** "I didn't trust the LLM to follow the rules, so the rules are code."

## Incident data model (unchanged from v1)

See `00_initial_plan.md` — Pydantic schema is good as-is.

## Cost model (v2 — concrete budgets)

- **Total dev budget: $30 LLM spend.** Hard stop via `cost_meter.py`. If we hit $25, we switch to cheaper models or smaller prompts.
- **Per-incident eval budget: $0.05.** Enforced by middleware; agent times out and falls back to "PR with raw logs" if exceeded.
- **Bake-off in week 1:** run 20 fixtures through both stacks (Claude haiku/sonnet vs. gpt-4o-mini/gpt-4o). Pick by `resolution_rate / $`.

---

# DELIVERABLE 2 — EVAL DATASET & METHODOLOGY (v2)

## Changes from v1

- **Cut public-issue mining and SO mining from the core benchmark.** Move to optional "wild" set of ~30 examples, marked separately in results, no statistical claim.
- **Core benchmark = 150 chaos-injected incidents.** 100 train / 50 held-out. Smaller than v1, faster to build, easier to defend ("all incidents are reproducible from seed + script — here's the script").
- **Adversarial set: 20 fixtures dedicated to guardrail testing.** Logs that try to trick the agent into `DROP TABLE`, ones that reference fake files, ones with prompt-injection strings.
- **Total: 150 core + 20 adversarial + 30 wild (stretch) = 170 mandatory + 30 stretch.**

## 12 chaos injectors (≥ 10 fixtures each = 120 minimum)

```
inject.schema_rename_column      ✦ auto-fix candidate
inject.schema_drop_column
inject.schema_retype_column
inject.null_spike
inject.upstream_5xx              (toxiproxy in front of mock API)
inject.oom                       (executor_config mem_limit)
inject.dag_syntax_error          ✦ auto-fix candidate
inject.dep_conflict
inject.duplicate_pk
inject.late_partition            ✦ auto-fix candidate
inject.auth_expire               (rotate fake secret)
inject.xcom_bloat                ✦ auto-fix candidate
```

Each injector:
- Takes `seed: int` for reproducibility
- Writes a `fixture.yaml` with full ground truth
- Snapshots the repo (`repo.tar.gz`), the schema (`schema.json`), and the resulting task log (`log.txt`)
- Records the chaos seed so any contributor can regenerate

## Metrics (unchanged from v1)

Resolution Rate, Class Acc, MTTR, Guardrail Catch, $/incident, Hallucination Rate, Coverage, Regression Rate.

## Baselines (v2 — same 4)

| Baseline | Implementation effort |
|---|---|
| B0: Restart-only | 10 LOC |
| B1: Rules-only (regex → templated fix) | ~200 LOC, one regex per class |
| B2: Single LLM call (logs pasted, no tools) | ~30 LOC |
| B3: Single LLM call + retrieval | ~80 LOC (uses pgvector from agent) |
| **Ours** | the whole repo |

## Contamination prevention (unchanged from v1)

---

# DELIVERABLE 3 — REVISED 6-WEEK BUILD PLAN (v2)

> **Two tracks every week**: A = agent/tools, B = eval/fixtures/metrics.

### Week 1 — Eval harness FIRST + reference-incident thin slice

**Outcome:** `replay.py` runs on 20 fixtures and prints a metrics table. The reference incident (`o_priority → priority` schema rename) goes through a *minimal* agent (3 tools, plain function calling) and opens a real PR on a local bare git repo. **Both ship in week 1.**

- [ ] Repo skeleton: `uv` workspace, ruff, mypy strict, pytest, pre-commit, GitHub Actions
- [ ] `docs/02_premortem.md` written
- [ ] Postgres + Airflow via `docker-compose.yml` (2 containers, not 5)
- [ ] One DAG `tpch_stg` with task `load_orders` (reads `o_priority`)
- [ ] One chaos injector: `inject.schema_rename_column` (deterministic seed)
- [ ] **Track B:** `fixture.py` writer + 20 fixtures generated (schema_rename only, varying seeds)
- [ ] **Track B:** `replay.py` runner + `metrics.py` (resolution_rate, class_acc, MTTR, $/incident)
- [ ] **Track B:** `baselines/b0_restart.py` and `baselines/b1_rules.py` both pass `replay.py`
- [ ] **Track A:** `cost_meter.py` middleware (logs every LLM call's tokens + $)
- [ ] **Track A:** minimal agent: `triage → diagnose → open_pr` with 3 tools (get_logs, diff_schema, open_pr)
- [ ] **Track A:** the agent runs on the 20-fixture set and produces a results row
- [ ] **Bake-off:** run agent w/ Claude stack vs. OpenAI stack on 20 fixtures; pick winner; document in `docs/03_model_choice.md`
- [ ] `make demo` script that injects the reference incident and prints the PR URL

**DoD:**
- `make eval` runs all 20 fixtures through 3 policies (B0, B1, ours), in < 3 min, prints a 3-row results table.
- `make demo` opens a real PR with a correct one-line SQL patch for the reference incident.
- Total LLM spend logged < $3.

**Risk + mitigation:**
- *Risk:* Airflow callback wiring eats 2 days. *Mitigation:* For week 1, skip the callback — chaos injector writes the incident row directly to Postgres. Real callback comes in week 3.

**Cut here if behind:** drop the bake-off, default to Claude haiku+sonnet, document choice as "convenience."

---

### Week 2 — Failure-class breadth (4 classes covered) + 80 fixtures

**Outcome:** Agent handles 4 of 10 classes; benchmark grows to 80 fixtures; per-class results table visible.

- [ ] Chaos injectors implemented: `schema_drop`, `schema_retype`, `null_spike`, `upstream_5xx`, `dag_syntax_error`
- [ ] **Track B:** 60 new fixtures (20 per added class × 3) → 80 total
- [ ] **Track A:** triage prompt v1 covers 10 classes (even if only 4 are *resolved*; others classified to "PR-only")
- [ ] **Track A:** `diagnose` prompt with structured output (Pydantic-validated JSON)
- [ ] **Track A:** `prompts/v1/*.md` checked in; `prompt_history` table row written on every change
- [ ] **Track A:** tool: `get_recent_diff` (GitPython, since last green run)
- [ ] **Track B:** `baselines/b2_single_llm.py` shipped
- [ ] **Track B:** Streamlit dashboard v0: per-class accuracy bar chart + confusion matrix
- [ ] Confusion matrix + per-class resolution rate added to README placeholder

**DoD:**
- `make eval` reports per-class breakdown; ≥ 4 classes show ≥ 70% resolution.
- Total fixtures: 80. Total LLM spend cumulative < $10.

**Risk + mitigation:**
- *Risk:* Chaos injectors flaky on macOS (esp. mem limits). *Mitigation:* run Airflow worker in Linux container; injectors target the container only.

**Cut here if behind:** drop `schema_retype` — hardest to make deterministic across pg versions.

---

### Week 3 — Sandbox + guardrails + adversarial set + real Airflow callback

**Outcome:** Agent verifies every proposed fix in a sandbox schema; 20 adversarial fixtures pass the guardrail bar; real Airflow `on_failure_callback` wired.

- [ ] **Track A:** `sandbox.py` — creates `sandbox_<incident_id>` schema from snapshot, runs `dbt build --target sandbox`, captures diff, drops schema on completion (or on timeout)
- [ ] **Track A:** Guardrail middleware: blast-radius, action budget, confidence gate, forbidden paths, hash-chained audit log, inverse-action rollback
- [ ] **Track A:** Real `on_failure_callback` posts to FastAPI `/incidents`
- [ ] **Track A:** Tool: `replay_in_sandbox(task)` — re-runs the failing task against the sandbox schema
- [ ] **Track B:** 20 adversarial fixtures: prompt-injection-in-logs, social-engineering-the-fix, fake-file-references, "ignore previous instructions"
- [ ] **Track B:** `metrics.py` adds Guardrail Catch Rate + Hallucination Rate
- [ ] **Track B:** Rollback CLI: `agent rollback <action_id>`
- [ ] `prompts/v2/*.md` — incorporates safety + structure lessons from week 2

**DoD:**
- Guardrail catch rate ≥ 95% on 20 adversarials.
- Sandbox-verified diff appears in PR body for every auto-fixable class.
- Real Airflow failure → incident row → agent run end-to-end, no manual step.
- Cumulative LLM spend < $15.

**Risk + mitigation:**
- *Risk:* Sandbox schema dbt builds take > 60s. *Mitigation:* pre-seed snapshot at incident-time; agent dbt-builds only the affected model + its direct upstream.

**Cut here if behind:** skip the inverse-action rollback CLI; document as "manual revert via `git revert` for now."

---

### Week 4 — Remaining classes + retrieval + observability + 150 fixtures

**Outcome:** All 10 classes detected, 7+ resolvable to ≥ 50% on train; pgvector retrieval working; full 150-fixture core benchmark complete.

- [ ] **Track A:** injectors for `oom`, `dep_conflict`, `duplicate_pk`, `late_partition`, `auth_expire`, `xcom_bloat`
- [ ] **Track A:** pgvector retrieval tool: `search_similar_incidents(k=5)` using embeddings of `(class, log_signature, exception_type)`
- [ ] **Track A:** structlog → JSON; OTel SDK wraps tool calls + LLM calls
- [ ] **Track B:** 70 new fixtures (across the 6 added classes) → 150 core total
- [ ] **Track B:** `baselines/b3_llm_plus_retrieval.py` shipped
- [ ] **Track B:** First end-to-end run on full 150 fixtures (train only; held-out 50 stays unseen)
- [ ] **Track B:** Streamlit dashboard: latency histogram, $/incident histogram, cost-vs-accuracy scatter
- [ ] `prompts/v3/*.md` based on per-class failure analysis

**DoD:**
- ≥ 100 train fixtures show ≥ 55% resolution rate.
- 4 baselines + ours all measured on train; results table populated.
- Cumulative LLM spend < $22.

**Risk + mitigation:**
- *Risk:* OOM injection is non-deterministic across machines. *Mitigation:* simulate OOM by injecting `MemoryError` raise in task code; record as "synthetic OOM" in fixture.

**Cut here if behind:** drop `dep_conflict` (hardest to make deterministic w/o real PyPI calls). Mention in limitations.

---

### Week 5 — Held-out eval, prompt iteration, contamination check, blog draft

**Outcome:** Final results on held-out 50 fixtures; blog post + README drafted; demo recorded.

- [ ] Run held-out 50 across all 4 baselines + ours, 3 random seeds each
- [ ] Contamination check script: hash every fixture input, grep all logged prompts for any match
- [ ] Memorization probe: 10 held-out fixtures sent to LLM with no tools, check for verbatim-fix leak
- [ ] Final prompt iteration sprint (v3 → v4 → v5), eval-gated: a prompt change only ships if held-out resolution stays within 95% CI
- [ ] README v1 written (per Deliverable 4 spec)
- [ ] Blog post draft (~1500 words)
- [ ] Loom recording (4 min) of reference-incident end-to-end
- [ ] Hero GIF generated (asciicast → GIF)

**DoD:**
- Held-out resolution rate ≥ 60% (target 70).
- All 4 baselines beaten on resolution rate AND $/incident.
- Contamination check shows zero hash matches.
- Cumulative LLM spend < $28.

**Risk + mitigation:**
- *Risk:* Held-out resolution rate < 50%. *Mitigation:* the blog becomes "where LLM agents fall short" — still publishable, still interview-worthy. Don't fake numbers.

**Cut here if behind:** drop the memorization probe; rely on hash check only.

---

### Week 6 — Polish, deploy dashboard, ship

**Outcome:** Public dashboard URL live; repo polished; LinkedIn post + thread published.

- [ ] Deploy dashboard to Streamlit Cloud (pinned to a `results.parquet` from final eval run)
- [ ] Deploy agent worker to Modal Labs (free tier, sleeps when idle) for a "try it live" button
- [ ] GitHub Actions: full eval CI on every PR (uses 20-fixture smoke set, not full 150 — < 2 min)
- [ ] Architecture diagram (Excalidraw → PNG) committed
- [ ] README final pass: hero metric at top, GIF, "60-second how-it-works," results table, limitations, 3-command quickstart
- [ ] Blog post final pass + cross-post (personal site → dev.to → Hacker News if it's good)
- [ ] LinkedIn post + Twitter thread published
- [ ] 3 STAR stories rehearsed (1-min, 3-min, 8-min versions)
- [ ] `CHANGELOG.md` and `LICENSE` (MIT) in place

**DoD:**
- Stranger can `git clone && make demo` on a fresh Mac and see a PR.
- Streamlit dashboard URL works.
- LinkedIn post live with metric in first line.
- Blog post published.

**Risk + mitigation:**
- *Risk:* Streamlit Cloud free tier rate-limits. *Mitigation:* dashboard reads a static `results.parquet` committed to repo; no live computation.

**Cut here if behind:** skip Modal deploy; demo is Loom + GIF only. Mention "live demo coming soon" in README footer.

---

# DELIVERABLE 4 — README + BLOG + LAUNCH (unchanged from v1)

See `00_initial_plan.md`. The narrative arc, titles, and STAR stories all still hold.

---

# What we build first

When the user says "go," we execute Week 1 in this order:

1. **Repo skeleton + tooling** (uv, ruff, mypy, pytest, pre-commit, GH Actions skeleton)
2. **`docs/02_premortem.md`** — explicit failure modes + mitigations
3. **`docker-compose.yml`** — Postgres + Airflow only
4. **`tpch_stg` DAG + `o_priority` reference incident**
5. **`chaos/inject.py` with `schema_rename_column`**
6. **20 fixtures generated (varying seeds)**
7. **`replay.py` + `metrics.py` + `baselines/b0_restart.py` + `baselines/b1_rules.py`**
8. **`cost_meter.py` middleware**
9. **Minimal agent (3 tools, plain function calling)**
10. **Bake-off: Claude vs. OpenAI on 20 fixtures**
11. **`make demo` + `make eval` targets**

That's week 1. We don't move to week 2 until `make eval` prints a real results table.
