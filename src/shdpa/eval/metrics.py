"""Metrics: resolution_rate, class_acc, mttr, $/incident, hallucination_rate.

Resolution scoring rules (semantic match against ground truth):
  - code_patch: ALL `must_include_strings` appear in proposed_fix_diff
                AND a non-empty diff exists
  - retry / config_change / secret_rotate / noop: predicted fix_kind matches exactly
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from shdpa.models import Incident


@dataclass
class IncidentScore:
    fixture_id: str
    predicted_class: str
    ground_truth_class: str
    class_correct: bool
    fix_kind_predicted: str
    fix_kind_truth: str
    fix_correct: bool
    resolved: bool        # produced an actionable result (PR or retry) matching ground truth
    hallucinated: bool    # diff references a string that does not appear in any repo file
    cost_usd: float
    latency_s: float
    error: str | None


def _diff_contains_all(diff: str, needles: Iterable[str]) -> bool:
    if not diff:
        return False
    return all(n.lower() in diff.lower() for n in needles)


def _grep_repo(repo_path: str, needles: Iterable[str]) -> set[str]:
    """Return the subset of needles that DO appear somewhere under repo_path."""
    if not repo_path:
        return set()
    p = Path(repo_path)
    if not p.exists():
        return set()
    haystack = ""
    for f in p.rglob("*"):
        if f.is_file() and f.suffix in {".sql", ".py", ".yml", ".yaml", ".txt", ".md"}:
            try:
                haystack += f.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
    found = set()
    h = haystack.lower()
    for n in needles:
        if n.lower() in h:
            found.add(n)
    return found


def score_incident(incident: Incident) -> IncidentScore:
    gt = incident.ground_truth
    assert gt is not None, "fixture must have ground truth"

    class_correct = incident.predicted_class == gt.failure_class
    fix_kind_truth = gt.fix.kind
    fix_kind_pred = incident.proposed_fix_kind or "noop"

    fix_correct = False
    if fix_kind_truth == "code_patch":
        fix_correct = (
            fix_kind_pred == "code_patch"
            and _diff_contains_all(
                incident.proposed_fix_diff or "", gt.fix.must_include_strings
            )
        )
    else:
        fix_correct = fix_kind_pred == fix_kind_truth

    resolved = class_correct and fix_correct and incident.error is None

    # hallucination: did the diff reference a symbol that doesn't exist in the repo?
    # OR did sandbox validation fail (indicating a compile/validation error / semantic hallucination)?
    hallucinated = False
    if incident.error and "sandbox_validation_failed" in incident.error:
        hallucinated = True
    elif incident.proposed_fix_diff:
        # check the strings the model said it included
        # only flag if it claims a column not present in either the diff or the repo
        # crude but effective for v0
        suspicious = [
            s for s in (gt.fix.must_include_strings or [])
            if s and s.lower() not in (incident.proposed_fix_diff or "").lower()
        ]
        present = _grep_repo(incident.repo_path, suspicious)
        hallucinated = bool(suspicious and not present)

    return IncidentScore(
        fixture_id=incident.fixture_id or str(incident.id),
        predicted_class=incident.predicted_class or "unknown",
        ground_truth_class=gt.failure_class,
        class_correct=class_correct,
        fix_kind_predicted=fix_kind_pred,
        fix_kind_truth=fix_kind_truth,
        fix_correct=fix_correct,
        resolved=resolved,
        hallucinated=hallucinated,
        cost_usd=incident.total_cost_usd,
        latency_s=incident.total_latency_s,
        error=incident.error,
    )


@dataclass
class Aggregate:
    n: int
    resolution_rate: float
    class_accuracy: float
    fix_kind_accuracy: float
    macro_f1: float
    mttr_s: float
    cost_total_usd: float
    cost_per_incident_usd: float
    hallucination_rate: float
    per_class: dict[str, dict[str, float]]


def aggregate(scores: list[IncidentScore]) -> Aggregate:
    if not scores:
        return Aggregate(0, 0, 0, 0, 0, 0, 0, 0, 0, {})
    n = len(scores)
    res = sum(s.resolved for s in scores) / n
    cls = sum(s.class_correct for s in scores) / n
    fix = sum(s.fix_correct for s in scores) / n
    mttr = sum(s.latency_s for s in scores) / n
    cost = sum(s.cost_usd for s in scores)
    cpi = cost / n
    halluc = sum(s.hallucinated for s in scores) / n

    # macro F1 over ground-truth classes
    classes = set(s.ground_truth_class for s in scores) | set(s.predicted_class for s in scores)
    f1s = []
    for c in classes:
        tp = sum(1 for s in scores if s.predicted_class == c and s.ground_truth_class == c)
        fp = sum(1 for s in scores if s.predicted_class == c and s.ground_truth_class != c)
        fn = sum(1 for s in scores if s.predicted_class != c and s.ground_truth_class == c)
        if tp + fp + fn == 0:
            continue
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        f1s.append(f1)
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0

    per_class: dict[str, dict[str, float]] = defaultdict(dict)
    counts = Counter(s.ground_truth_class for s in scores)
    for cls_name, cnt in counts.items():
        cls_scores = [s for s in scores if s.ground_truth_class == cls_name]
        per_class[cls_name] = {
            "n": cnt,
            "resolution_rate": sum(s.resolved for s in cls_scores) / cnt,
            "class_accuracy": sum(s.class_correct for s in cls_scores) / cnt,
        }

    return Aggregate(
        n=n,
        resolution_rate=res,
        class_accuracy=cls,
        fix_kind_accuracy=fix,
        macro_f1=macro_f1,
        mttr_s=mttr,
        cost_total_usd=cost,
        cost_per_incident_usd=cpi,
        hallucination_rate=halluc,
        per_class=dict(per_class),
    )
