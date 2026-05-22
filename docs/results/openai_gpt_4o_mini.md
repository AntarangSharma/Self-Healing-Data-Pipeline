# Real-LLM Eval — OpenAI GPT-4o-mini, Prompts v3

Provider: `openai` · Model: `gpt-4o-mini` · Prompts: `prompts/v3/`
Fixtures: 100 (10 per class × 10 classes, deterministic seed)
Date: 2026-05-21

## Headline Comparison

| Metric | Claude Sonnet 4 | **GPT-4o-mini** | Δ |
|---|---|---|---|
| **Resolved** | 90 / 100 = 90 % | **80 / 100 = 80 %** | -10 pp |
| **Class accuracy** (triage) | 100 % | **95 %** | -5 pp |
| **Fix-kind accuracy** | 90 % | **80 %** | -10 pp |
| **Hallucination rate** | **0 %** | **5 %** | +5 pp |
| **MTTR** | 6.15 s | **4.80 s** | -1.35 s |
| **$ / incident** | $0.0098 | **$0.0018** | **-$0.0080** |
| **Total run cost (100 runs)** | $0.98 | **$0.18** | **-$0.80** |

---

## Performance Deep-Dive

### Triage Success
`gpt-4o-mini` exhibits exceptional classification accuracy, correctly triaging **95%** of failure signatures. The 5% misclassifications were primarily concentrated in complex, overlapping tracebacks where dbt null-check errors resembled generic `schema_drift` column drop patterns.

### Hallucination Risk
At **5%**, the hallucination rate is a critical factor for SRE teams. Unlike `claude-sonnet-4`, `gpt-4o-mini` occasionally fails on *case-sensitivity* matching (proposing `UPPERCASE` columns when the repository contains lowercase ones) or makes inaccurate replacements in complex multi-file scenarios like `wild_similar_columns`. 

### The Cost/Speed Winning Formula
While `gpt-4o-mini` drops 10% in resolution rate compared to Sonnet 4, its **MTTR is 1.35 seconds faster**, and it is **81% cheaper** ($0.0018 vs. $0.0098 per incident). For non-critical pipelines or staging environments, `gpt-4o-mini` represents the ideal cost-efficient choice.
