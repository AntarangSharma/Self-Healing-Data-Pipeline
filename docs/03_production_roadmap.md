# Production Roadmap — What's Left to Make This a Real Product

> **Current state (May 2026):** The agent is *portfolio-ready*. It does what it claims, on a deterministic harness, with honest numbers (90 % resolved / 0 % hallucination on Claude Sonnet 4, v3 prompts, n=20). That's enough to interview off and demo on a laptop.
>
> **Goal of this doc:** be honest about the gap between "portfolio-ready" and "I would deploy this against my company's Airflow." There is a gap. This file lists every concrete thing in it.

---

## Legend

| Symbol | Meaning |
|---|---|
| **P0** | Must have before *any* production deploy. Without it, the agent is unsafe or unusable. |
| **P1** | Required for real-team adoption. Without it, the agent works but ops won't like you. |
| **P2** | Nice-to-have. Improves UX, cost, or differentiation but not a blocker. |
| ✅ | Already shipped — listed here for context only. |

Effort estimates are rough; "day" = one focused engineer-day.

---

## 1. Triggering & integration

The agent currently only fires when you manually replay a fixture. A real product needs to be *called* by something.

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 1.1 | **Airflow `on_failure_callback` plugin** that POSTs the incident JSON to the agent | **P0** | 1 day | The `airflow_callback` literal already exists in `models.Incident.source`; nothing actually uses it. |
| 1.2 | **`docker-compose.yml`** with Airflow 2.x + Postgres + the agent as a sidecar, plus a seeded DAG that fails on purpose so a new user can `docker compose up` and see end-to-end behavior in 60 s | **P0** | 1 day | The README has been promising "Week-2 work" since v1; ship it. |
| 1.3 | **dbt-failure adapter** — `on-run-end` hook that turns a dbt test failure into an `Incident` | P1 | 0.5 day | dbt is the other half of the Airflow/dbt stack the agent claims to serve. |
| 1.4 | **GitHub Actions adapter** — let CI failures (not just runtime failures) call the agent | P2 | 0.5 day | Different failure-class distribution; would need new fixtures. |
| 1.5 | **HTTP `/incident` endpoint** (FastAPI) so anything that emits webhooks can drive it | P1 | 0.5 day | Currently the only interface is `python -m shdpa.eval.replay`. |

---

## 2. Safety, validation, and "did the fix actually work?"

The agent proposes a patch, opens a PR, and *hopes* the patch compiles. A real product verifies.

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 2.1 | **Patch-validation sandbox** — apply the proposed diff to a throwaway Postgres + dbt project, run the failing task, assert it now passes, **only then** open the PR | **P0** | 1 day | This is the single highest-value remaining feature. Turns "90 % resolved" into "90 % resolved AND verified to compile." Catches the residual hallucinations the regex grep misses. |
| 2.2 | **Rollback path** — if a merged PR causes a green→red transition within N runs, automatically revert | P1 | 1 day | The agent currently has no concept of "did my fix break something later?" |
| 2.3 | **Patch dry-run mode** — `--dry-run` flag that shows the proposed PR but never opens it; required for new-team onboarding | P1 | 0.25 day | Currently the agent has `dry_run` on Action but it's wired through the codepath, not the CLI. |
| 2.4 | **Multi-step refactor cap** — if more than 3 patches in 24 h target the same file, escalate ("the agent is in a loop") | P1 | 0.5 day | Cheap safety net; prevents thrashing. |
| 2.5 | **Patch-validation in CI** — every PR the agent opens runs through the normal CI pipeline; if CI fails, the agent comments the failure and closes itself | **P0** | 0.5 day | Trivial GitHub Action; closes the loop. |

---

## 3. Storage, audit, and state

Today every `run_agent` lives in memory and dies. Production needs persistence.

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 3.1 | **SQLite incident store** — every triage/diagnose/action/cost row written to disk; queryable via `shdpa incidents list/show` | **P0** | 0.5 day | Required for any compliance review or "what did the agent do last night?" question. |
| 3.2 | **Postgres backend option** for multi-instance deployment | P2 | 0.5 day | Migration from SQLite is straightforward. |
| 3.3 | **Immutable audit log** — every LLM prompt + completion + cost + final action hashed and append-only | **P0** | 0.5 day | Without this you cannot answer "why did the agent decide X?" three weeks later. |
| 3.4 | **PII / secret redaction** in `log_text` before it ever reaches the LLM | **P0** | 0.5 day | Right now an Airflow log containing an API key gets shipped to Anthropic verbatim. This is a real legal/security hole. |
| 3.5 | **Retention policy** — auto-prune incidents older than N days, keep aggregates | P2 | 0.25 day | |

---

## 4. Escalation & human-in-the-loop

The README claims the agent "escalates to humans" for `oom`, `auth_expiry`, `unknown` — but the actual behavior is `kind="noop"` with a log line. Nothing pages anyone.

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 4.1 | **Slack escalation webhook** — non-auto-fix classes post a structured message to a channel with the evidence dump | **P0** | 0.25 day | The single biggest "you said it but didn't do it" gap. |
| 4.2 | **PagerDuty integration** for severity ≥ P2 + auth_expiry | P1 | 0.5 day | |
| 4.3 | **PR-comment approval flow** — for non-whitelisted classes, the agent posts the proposed fix as a draft PR comment and waits for `/approve` | P1 | 0.5 day | Lets you trial-run the agent in "supervised" mode on classes you don't trust yet. |
| 4.4 | **Reviewer feedback loop** — record merge/close/edit outcomes for every PR the agent opened, use as training signal for prompt v4 | P1 | 1 day | Closes the eval loop. |

---

## 5. Observability & ops

You can't run something in production that you can't see.

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 5.1 | **Prometheus `/metrics` endpoint** — counters for incidents/class, resolution rate, cost, p50/p95/p99 latency | **P0** | 0.5 day | |
| 5.2 | **Pre-built Grafana dashboard** JSON committed to `ops/grafana/` | P1 | 0.5 day | |
| 5.3 | **Structured-log shipping** — `structlog` is already in place; add OTLP exporter | P1 | 0.25 day | |
| 5.4 | **Cost dashboard** — per-team / per-repo / per-class $ breakdown | P1 | 0.5 day | Required before finance signs off. |
| 5.5 | **SLO doc** — target 95 % of `schema_drift` incidents resolved within 60 s; commit + alert on breach | P2 | 0.25 day | |
| 5.6 | **Performance budget** in CI — fail the build if p95 latency exceeds N seconds on the fixture set | P2 | 0.25 day | Prevents prompt v5 from being 3× slower without anyone noticing. |

---

## 6. Cost efficiency

Right now every class goes to Claude Sonnet 4 at $0.01/incident. Easy wins:

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 6.1 | **Per-class model routing** — triage on Haiku ($0.001), diagnose on Sonnet only when triage is uncertain | P1 | 0.5 day | Plausibly 3× cost reduction with no quality loss. |
| 6.2 | **Prompt-cache warming** for the system prompts (Anthropic supports it natively) | P2 | 0.25 day | ~30 % token savings on a repeated prompt. |
| 6.3 | **Local LLM fallback** — `llama3.1:8b` via Ollama for shops that can't send logs to a cloud LLM | P1 | 0.5 day | Provider abstraction is already there; just needs an eval pass. |
| 6.4 | **Provider failover** — if Anthropic returns 5xx for > N seconds, fall back to OpenAI | P1 | 0.25 day | |
| 6.5 | **Batch mode** — process N incidents in one prompt for offline backfills | P2 | 0.5 day | |

---

## 7. Security & compliance

The current threat model: "the developer who runs the agent is trusted." That doesn't fly in any org of size.

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 7.1 | **Secret management** — API keys read from Vault / AWS Secrets Manager, not `os.getenv` | **P0** | 0.5 day | |
| 7.2 | **Per-repo allow-list** — agent will only touch repos in a config-controlled set | **P0** | 0.25 day | Currently the agent will happily PR against *any* repo path you hand it. |
| 7.3 | **RBAC on the HTTP endpoint** (item 1.5) — who is allowed to file an incident | P1 | 0.5 day | |
| 7.4 | **GitHub App** (vs. `gh` CLI) — least-privilege scoped token per repo | P1 | 1 day | The `gh` CLI requires interactive auth; not viable in a service. |
| 7.5 | **Audit-log signing** — append-only with HMAC so an admin can't quietly delete a row | P2 | 0.5 day | |
| 7.6 | **SOC 2 evidence trail** — every action ties to an actor (the calling service) and a reason | P2 | 0.5 day | Only matters if you actually need to be SOC 2 compliant. |

---

## 8. Evaluation & quality

The eval is good but not yet *trustworthy* in a statistical sense.

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 8.1 | **Variance run** — repeat the n=20 real-LLM eval 5×, report mean ± stddev. Currently a single point estimate. | P1 | 5 min compute, ~$1 | One run of the existing harness; just needs $$$. |
| 8.2 | **Multi-LLM matrix** — re-run the eval on `gpt-4o-mini`, `claude-3-5-haiku`, `claude-opus-4`, `llama3.1:8b`, commit the price/quality grid | P1 | 30 min compute, ~$5 | Strongest single piece of evidence for "this is provider-agnostic." |
| 8.3 | **Wild-fixture real-LLM run** — the wild set has only been mock-eval'd. Burn ~$0.05 to get the real number. | P1 | 5 min, $0.05 | |
| 8.4 | **Held-out fixture set from public Airflow issues** — scrape ~20 real incidents from GitHub issues, hand-label, run eval | P1 | 1 day | The single strongest credibility move. "Works on synthetic fixtures" is one thing; "works on incidents real engineers actually filed" is another. |
| 8.5 | **Prompt regression test** — `pytest tests/test_prompt_eval.py` that asserts v3 still hits ≥85 % on a frozen 10-fixture set; fails the CI if anyone breaks a prompt | P1 | 0.25 day | |
| 8.6 | **A/B harness** — run the same incident through prompts vN and vN-1 in parallel, log which produced the merged PR | P2 | 1 day | Required to make data-driven prompt decisions at scale. |
| 8.7 | **Adversarial fuzzer** — auto-generate prompt-injection attempts in log lines; current adversarial set is only 4 hand-crafted attacks | P2 | 1 day | |

---

## 9. UX & operator tooling

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 9.1 | **Web dashboard** — list incidents, view evidence, see proposed diff, approve/reject | P1 | 2 days | Single biggest UX deliverable. Even a 200-LOC FastAPI + HTMX page beats a CLI. |
| 9.2 | **`shdpa replay <pr-number>`** — re-run the agent on the incident that produced PR #N, useful for prompt iteration | P2 | 0.25 day | |
| 9.3 | **Loom-style architecture walkthrough** in `docs/` | P2 | 0.5 day | Currently have asciinema demo + PDF, missing whiteboard video. |
| 9.4 | **Inline prompt diff viewer** — `shdpa diff-prompts v2 v3` to see what changed | P2 | 0.25 day | |
| 9.5 | **Cost-preview mode** — print the estimated $ before actually calling the LLM | P2 | 0.25 day | |

---

## 10. Documentation

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 10.1 | **Runbook** for on-call: "agent is broken, here's how to disable it / drain the queue / rollback its PRs" | **P0** | 0.5 day | |
| 10.2 | **API reference** for the HTTP endpoint (item 1.5) | P1 | 0.25 day | |
| 10.3 | **Threat-model doc** — the explicit security assumptions and the boundaries the agent will not cross | P1 | 0.5 day | |
| 10.4 | **Prompt-engineering guide** — how to write a v4 prompt for a new failure class | P2 | 0.5 day | |
| 10.5 | **Failure-class taxonomy doc** — formal definition of each of the 11 classes with positive/negative examples | P2 | 0.5 day | |

---

## 11. Coverage of failure classes

Today the auto-fix whitelist covers 5 of 11 classes. Real production failures have a long tail.

| # | Item | Priority | Effort | Notes |
|---|---|---|---|---|
| 11.1 | **`oom` config-change handler** — for known small bumps (1G → 2G), propose a PR; for big jumps, escalate | P1 | 0.5 day | Currently always escalates, including trivial cases. |
| 11.2 | **`auth_expiry` rotation hook** — call into a secret manager API to rotate, then retry the task | P1 | 1 day | The hardest one because it requires an external integration. |
| 11.3 | **New class: `data_freshness`** — partition X hours late, sensor timed out | P2 | 0.5 day | Common; not in the taxonomy yet. |
| 11.4 | **New class: `cost_anomaly`** — query cost spike (Snowflake / BigQuery) | P2 | 1 day | Increasingly common ask. |
| 11.5 | **New class: `pii_leak`** — DLP detection in pipeline output | P2 | 2 days | High-value but high-complexity. |

---

## 12. Things I deliberately don't think you should build

These look attractive but the ROI isn't there for this codebase:

- **LangGraph migration.** The plain function-calling loop is ~150 LOC and the eval moves; LangGraph adds dependency surface for no measurable win. The README already gates this on "if the eval moves" and it hasn't.
- **Fine-tuned model.** A 90 % zero-shot result with $0.01/incident is already excellent. Fine-tuning makes sense at 10× the volume.
- **Vector-DB-backed RAG over the repo.** The `repo_files` listing + `git_diff` tool is already plenty of context; adding embeddings adds latency and infra for marginal gain. Revisit only if a real-world fixture shows the LLM needs more.
- **GUI prompt editor.** Prompts live in `prompts/v*/*.md` and are diff-friendly. A GUI would make worse prompts faster.
- **Multi-tenant SaaS.** Don't build hosted-SaaS infrastructure for a tool that 90 % of users will self-host.

---

## What "v1.0 production release" actually means

A defensible v1.0 release should bundle **everything marked P0 above**, plus items 1.1, 1.2, 4.1, 5.1, 8.4 from P1. Total effort estimate:

| Bucket | Days |
|---|---|
| All P0 items | ~6 days |
| Cherry-picked P1 (Airflow plugin, Slack, Prometheus, wild eval, held-out set) | ~4 days |
| Buffer for integration & polish | ~2 days |
| **Total** | **~12 engineer-days** |

That's a clean 2.5-week sprint for one engineer who already knows the codebase. After which: shippable.

---

## What's already done — for reference

✅ 6-stage agent loop (triage → diagnose → plan → guardrails → act → report)
✅ LLM provider abstraction (mock / openai / anthropic / ollama)
✅ Cost meter with hard budget cap + 6 safety tests
✅ Deterministic guardrails (forbidden paths, blast radius, destructive-SQL scan, auto-fix whitelist)
✅ 11 failure-class taxonomy
✅ 10 chaos injectors + 4 adversarial fixtures + 5 wild fixtures
✅ Three honest baselines (B0/B1/B2) with documented hallucination rates
✅ Prompts v1 → v2 → v3 with regenerate-on-incomplete loop (3 attempts max)
✅ `gh`-CLI-aware PR tool with bare-repo fallback
✅ 27 unit tests + 4 integration tests (skipif markers)
✅ Real-LLM eval: 90 % resolved, 0 % hallucination on Claude Sonnet 4
✅ Eval-run fixture isolation via tmpdir
✅ Case-insensitive `_plan_files` for SQL keyword tolerance
✅ `unknown` class always-escalates rather than guessing
✅ Mermaid architecture diagram
✅ Beginner-friendly explainer PDF
✅ 14-second asciinema demo

---

*Last updated: 2026-05-21. Maintained by the same engineer who wrote the code; if it's stale it's because something else mattered more that day.*
