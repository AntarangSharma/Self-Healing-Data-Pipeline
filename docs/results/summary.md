# Eval Results — 50 fixtures (5/class × 10 classes)

Generated with mock LLM provider on Thu May 21 15:16:43 PDT 2026.

| Policy | n | Resolved | Class Acc | Hallucination | $/incident | MTTR |
|---|---|---|---|---|---|---|
| b0 | 50 | 0% | 0% | 0% | $0.0000 | 0ms |
| b1 | 50 | 62% | 100% | 8% | $0.0000 | 0ms |
| b2 | 50 | 0% | 100% | 0% | $0.0000 | 0ms |
| ours | 50 | 100% | 100% | 0% | $0.0000 | 81ms |

## Per-class resolution (ours)

| Class | n | Resolved | Class Correct |
|---|---|---|---|
| auth_expiry | 5 | 100% | 100% |
| dag_import | 5 | 100% | 100% |
| dep_conflict | 5 | 100% | 100% |
| disk_full | 5 | 100% | 100% |
| idempotency | 5 | 100% | 100% |
| null_spike | 5 | 100% | 100% |
| oom | 5 | 100% | 100% |
| schema_drift | 10 | 100% | 100% |
| upstream_5xx | 5 | 100% | 100% |
