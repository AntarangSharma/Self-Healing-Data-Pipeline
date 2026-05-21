# Pre-Mortem — Self-Healing Data Pipeline Agent

> Imagine it's 2026-07-09 (8 weeks from today). The project shipped but didn't land.
> Recruiters skim the README and move on. Nobody stars the repo. Why did that happen?
> This doc lists the 10 likeliest failure modes and a concrete mitigation for each.
> Re-read this at the start of every week.

| # | Failure mode | Probability | Impact | Early signal | Mitigation |
|---|---|:---:|:---:|---|---|
| 1 | **Eval set is built last, can't show the result** | High | Critical | Week 3 ends with no `make eval` output | Week 1 ships `replay.py` + 20 fixtures + 2 baselines. Non-negotiable. |
| 2 | **LLM resolution rate < 50% on held-out** | Medium | Critical | Train rate < 60% by end of week 4 | Pivot blog to "where LLM agents fall short"; that's still a great post. Don't fake numbers. |
| 3 | **Sandbox (DinD or schema) takes 3 days to debug** | Medium | High | Week 3 day 2 still fighting it | v2 already swapped DinD → Postgres schema. If schema approach also stalls, drop sandbox entirely and mark all auto-fixes as "PR-only" — still a valid project. |
| 4 | **Chaos injectors aren't deterministic across machines** | Medium | High | Different seeds → different ground truth | Generate all fixtures on ONE machine (CI runner); commit the resulting fixtures as artifacts. Don't ask contributors to regenerate. |
| 5 | **LLM cost blows the $30 budget by week 4** | Medium | Medium | `cost_meter.py` shows > $20 by week 3 | Switch diagnose model to cheapest tier; shrink prompts; cap tool-call iterations at 4. |
| 6 | **Prompt contamination from training data of public Airflow issues** | Medium | High | Memorization probe leaks ground-truth fix | Already mitigated: v2 cuts public-issue mining from core benchmark. |
| 7 | **Airflow `on_failure_callback` plumbing eats a week** | High | Medium | Day 3 of week 1 still wiring it | v2 already addresses: week 1 skips the callback (chaos writes incident directly to DB). Real callback in week 3. |
| 8 | **Reference incident demo is flaky on fresh clone** | High | Critical (recruiter-facing) | A teammate's fresh clone fails `make demo` | Make `make demo` the most-tested code path. CI runs `make demo` end-to-end on every push. |
| 9 | **Blog post written in the last 2 days, sounds rushed** | High | High | Week 5 ends without a draft | v2 already addresses: blog draft is a week 5 DoD item, not a week 6 task. |
| 10 | **No clear hero metric — README opens with feature list, not a number** | Medium | High | Draft README opens with "This project..." | First line of README must be: "Resolves X% of [N] benchmarked Airflow failures, [Y]s avg, [$Z]/incident." Numbers visible above the fold or rewrite. |

## Red lines (project gets paused, not pushed through)

- Cumulative LLM spend hits $30 → pause, audit, pick cheaper models before continuing.
- End of week 3 and no real Airflow callback → cut Airflow integration entirely, demo via chaos injector alone, mention as limitation.
- End of week 4 and < 100 fixtures → stop building agent, spend a full week on fixtures.
- End of week 5 and < 50% held-out resolution → pivot blog narrative, do NOT fake numbers.

## Anti-patterns to actively avoid

1. Adding LangGraph/Dagster/Kafka because they look good on resume.
2. Spending more than 4 hours on observability dashboards before week 4.
3. Tuning a prompt without an eval to measure the change.
4. Writing more than 50 LOC of code without a test for it.
5. Editing the README before week 5 (it'll be wrong).
6. Adding a failure class to the taxonomy without a chaos injector for it.
7. "I'll fix this later" comments — file an issue or fix now.
