# Threat model — `shdpa` agent

> STRIDE-style, deliberately short. The agent is a piece of code that takes a log line and opens a PR. That's the surface area; the threats are the ways that surface gets abused.

---

## 1. Assets

| Asset | Sensitivity | Why an attacker wants it |
|---|---|---|
| LLM API keys (Anthropic, OpenAI) | High | $$$ on someone else's bill |
| Source repos the agent can PR against | High | Code execution at merge time → supply-chain attack |
| Customer PII in pipeline logs | High | GDPR / CCPA fines |
| SQLite incident DB (`shdpa.db`) | Medium | Reveals which pipelines fail, when, how |
| Slack / PagerDuty webhook URLs | Medium | Spam / DoS the on-call rotation |
| Audit log integrity | High | "What did the agent do?" for compliance |

## 2. Trust boundaries

```
┌─────────────┐   POST /incidents    ┌──────────────────┐
│  Airflow    │ ───────────────────▶ │   shdpa agent    │
│  (DAG run)  │   (TLS, RBAC?)       │   (this repo)    │
└─────────────┘                      └────────┬─────────┘
                                              │ HTTPS
                                              ▼
                                     ┌──────────────────┐
                                     │  LLM provider    │
                                     │  (Anthropic etc) │
                                     └──────────────────┘
                                              │
                                              ▼ git push (PAT/App)
                                     ┌──────────────────┐
                                     │  GitHub repo     │
                                     └──────────────────┘
```

The agent process IS the trust boundary between the noisy world (logs from arbitrary DAGs) and the high-trust world (the LLM + the repo). Everything entering must be sanitised; everything leaving must be auditable.

## 3. STRIDE walkthrough

### S — Spoofing
| Threat | Mitigation |
|---|---|
| Attacker POSTs a fake `Incident` to `/incidents` | Add RBAC (P1, item 7.3) — bearer token or mTLS in front. Today: trust the network. |
| Attacker hijacks Slack webhook URL | URL is treated as a secret (item 7.1, secret manager). Rotate on suspicion. |

### T — Tampering
| Threat | Mitigation |
|---|---|
| Operator quietly deletes an incident from the DB | `audit_log` is append-only with SHA256 of the JSON blob. `shdpa verify-audit` flags any row whose hash no longer matches. |
| MitM modifies LLM response in flight | HTTPS to provider; cost meter would catch impossibly-cheap-completions. |
| Attacker tampers with `prompts/v3/*.md` | Prompts are in-repo + signed by commits; PR review covers this. |

### R — Repudiation
| Threat | Mitigation |
|---|---|
| "I never approved that PR" | `/approve` workflow requires a comment from a write-perm user; GH stores the audit. |
| "The agent did X without authorisation" | `audit_log` records every action with the originating incident id + timestamp. |

### I — Information disclosure
| Threat | Mitigation |
|---|---|
| **Log line contains an API key / customer PII; gets shipped to the LLM provider** | `middleware/redact.py` runs BEFORE every LLM call; 13 patterns including AWS / OpenAI / Anthropic / GitHub keys, JWTs, SSH keys, DB URLs, emails, credit cards. |
| Incident DB readable by anyone on the host | Default path is `/data/shdpa.db` inside the container, volume-mounted with restrictive perms. |
| LLM provider trains on our prompts | Anthropic / OpenAI both expose "no-training" options in their API; use them. Documented in runbook §1. |

### D — Denial of service
| Threat | Mitigation |
|---|---|
| Attacker floods `/incidents` to burn API budget | `CostMeter` total cap ($30 default); over-cap incidents short-circuit to `noop`. Per-incident cap ($0.05). |
| Compromised DAG triggers callback in an infinite loop | Multi-step refactor cap (guardrail) — ≥3 patches/24h targeting the same file → escalate, no new PRs. |
| Prompt-injection makes the agent re-prompt itself N times | `max_attempts=3` hard-coded in the regenerate-on-incomplete loop. |

### E — Elevation of privilege
| Threat | Mitigation |
|---|---|
| **Prompt injection in a log line tries to get the agent to PR `infra/*` or `secrets/*`** | `forbidden_paths` guardrail blocks at the structural level. Tested in `fixtures_adversarial/`. |
| Agent PRs against a sibling repo it has no business in | `SHDPA_ALLOWED_REPOS` glob-list — incident outside the list short-circuits to `noop` with rule `repo_not_allowed`. |
| `gh` CLI runs with broad PAT scope | Use a GitHub App with least-privilege per-repo install (item 7.4). |
| LLM emits `DROP TABLE` and it slips through review | Destructive-keyword guardrail (`DROP TABLE`, `TRUNCATE`, `DELETE FROM`, `rm -rf`) blocks the action; tested in 4 adversarial fixtures. |

## 4. Out of scope

These are real concerns but we don't claim to mitigate them today:

- **Compromised maintainer.** If someone with merge rights on the agent's repo ships a malicious prompt, the agent will do whatever the prompt says. PR review is the only line of defence.
- **Compromised LLM provider.** If Anthropic ships a backdoored model that emits `DROP TABLE` for `oom` failures, the destructive-keyword guardrail catches the obvious case but not subtle ones.
- **Side-channel attacks** (timing, cost, prompt-cache) against the agent. Possible but extremely low ROI for an attacker compared to just submitting a malicious DAG.

## 5. Periodic review

This doc is checked into the repo on purpose. Re-review:
- Quarterly
- After any incident class is added to `AUTO_FIX_WHITELIST`
- After any new tool is registered in `tools/registry.py`
- After every adversarial-fixture run that finds a new attack
