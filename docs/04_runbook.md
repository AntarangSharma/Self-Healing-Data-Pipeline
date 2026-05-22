# On-call runbook — `shdpa` in production

This is the doc you read at 3 AM when the agent itself is on fire. It assumes the docker-compose deployment from `docker-compose.yml`; the principles transfer to any orchestrator.

---

## 1. First-five-minutes triage

| Symptom | First check | Likely cause |
|---|---|---|
| `/healthz` returns 200 but `/readyz` returns 503 | `docker compose logs shdpa \| tail -50` | DB volume mount lost / permissions |
| Resolution rate dropped from ~90 % → < 30 % overnight | `curl /stats` then `curl /metrics \| grep shdpa_guardrail_blocks` | Model regressed or prompt change shipped |
| `shdpa_llm_cost_usd_total` graph elbow-up | `curl /stats` | Runaway re-prompts (regenerate-on-incomplete in a loop) |
| Slack/PD silent for 30 min | `docker exec shdpa env \| grep SHDPA_ESCALATION_DRYRUN` | Dryrun left on |
| Guardrail rule `repo_not_allowed` spiking | `docker exec shdpa env \| grep SHDPA_ALLOWED_REPOS` | Glob list is too tight after a repo move |

Always grab these two artifacts before pulling any lever:
```bash
docker compose logs --since=1h shdpa > /tmp/shdpa.log
curl -s http://shdpa:8080/metrics > /tmp/shdpa.metrics
```

---

## 2. Kill switches (use in this order)

1. **Soft-disable auto-PR (safest)** — set `SHDPA_DRY_RUN=true` and restart. Agent still triages + diagnoses but emits `noop` instead of opening PRs. Costs ~$0.01/incident; zero blast radius.
2. **Hard-disable LLM (no API spend)** — set `SHDPA_LLM_PROVIDER=mock`. Agent uses the regex fallback. Useful when a provider outage triggers retry storms.
3. **Lock the repo allow-list** — `SHDPA_ALLOWED_REPOS=/repo/that/you/trust`. Any incident pointing at a different `repo_path` short-circuits to `noop` with rule `repo_not_allowed`.
4. **Stop accepting incidents** — `docker compose stop shdpa`. Airflow callbacks will get connection-refused; the on-call handles failures the old way until you're back.

---

## 3. Metrics that matter

Scrape `/metrics` into Prometheus. Suggested alerts:

```yaml
- alert: ShdpaResolutionRateDropped
  expr: shdpa_last_resolution_rate < 0.6
  for: 30m
  labels: { severity: page }
  annotations:
    summary: "shdpa resolution rate {{ $value }} (expected ≥ 0.85)"

- alert: ShdpaCostSpike
  expr: increase(shdpa_llm_cost_usd_total[1h]) > 5
  for: 15m
  labels: { severity: page }
  annotations:
    summary: "shdpa spent >$5 in the last hour"

- alert: ShdpaGuardrailFloodForbiddenPath
  expr: increase(shdpa_guardrail_blocks_total{rule="forbidden_path"}[15m]) > 10
  for: 5m
  labels: { severity: page }
  annotations:
    summary: "shdpa blocked >10 forbidden_path attempts in 15m — possible prompt-injection attack"

- alert: ShdpaNoIncidentsProcessed
  expr: rate(shdpa_incidents_total[1h]) == 0
  for: 1h
  labels: { severity: ticket }
  annotations:
    summary: "shdpa hasn't processed an incident in 1h — is the Airflow callback wired?"
```

---

## 4. Audit log — proving what the agent did

Every incident is hashed at write time. To verify nothing has been tampered with:

```bash
docker exec shdpa python -c "
from shdpa.storage import get_default_store
bad = get_default_store().verify_audit()
print('OK' if not bad else f'{len(bad)} tampered rows: {bad[:3]}')
"
```

This is the artifact you hand to security/compliance after an incident. The SHA chain is append-only — even `INSERT OR REPLACE` writes a new audit row.

---

## 5. Incident classes the agent will NOT auto-fix

These are designed to escalate. **Do not "fix" the agent to handle them silently.**

| Class | Why escalation is correct |
|---|---|
| `oom` | Bumping a worker memory limit from a log line is how you cascade-fail a whole cluster. |
| `auth_expiry` | Secret rotation is out-of-band by policy. The agent emits `secret_rotate` so a human runs the playbook. |
| `unknown` | Triage couldn't classify. Auto-fixing an unclassified failure is the textbook agent footgun. |

If you see escalations for these classes, that's the agent working as designed. Investigate the underlying pipeline issue, not the agent.

---

## 6. Common debugging commands

```bash
# Tail structured logs (JSON) filtered to one incident:
docker compose logs shdpa | grep '"incident_id": "abc123…"' | jq .

# Re-run a single incident against the live agent:
curl -X POST http://shdpa:8080/incidents \
     -H 'content-type: application/json' \
     --data @incident.json | jq .resolved

# Replay the eval suite against the deployed agent (sanity check after a deploy):
make eval

# Dump all incidents in the last 24 h to a CSV for a postmortem:
docker exec shdpa python -c "
import csv, sys, datetime as dt
from shdpa.storage import get_default_store
s = get_default_store()
rows = s.list_incidents(limit=10000,
    since=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1))
w = csv.DictWriter(sys.stdout, fieldnames=rows[0].keys())
w.writeheader(); w.writerows(rows)
" > incidents.csv
```

---

## 7. Restoring after a bad deploy

```bash
# Roll back the image
docker compose pull shdpa
docker compose up -d shdpa

# If the bad version corrupted prompts, force prompts v3:
docker compose exec shdpa env SHDPA_PROMPT_VERSION=v3 shdpa eval --fixtures fixtures --policy ours

# Compare to last known-good results (committed in docs/results/)
diff <(jq -s '.[].resolved' results.jsonl | sort | uniq -c) \
     <(jq -s '.[].resolved' docs/results/v3_run_anthropic_n20.jsonl | sort | uniq -c)
```

The `docs/results/` JSONLs are committed deliberately: they're the regression baseline you compare against, not just nice graphs for the README.

---

## 8. Escalation policy

For anything not covered above:

1. Open an issue in the repo with the logs + metrics snapshots from §1.
2. Page the agent owner ONLY if `shdpa_incidents_total` is increasing AND `shdpa_last_resolution_rate < 0.5`.
3. Everything else can wait until business hours — the worst case of "agent is down" is that Airflow falls back to its old behavior (page the on-call), which is what was happening before this project existed.
