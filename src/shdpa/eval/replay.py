"""Eval runner. Loads fixtures, runs a policy on each, prints + saves results.

Usage:
  python -m shdpa.eval.replay --fixtures fixtures --policy ours
  python -m shdpa.eval.replay --fixtures fixtures --policy b0,b1,b2,ours --out results.jsonl
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from rich.console import Console
from rich.table import Table

from shdpa.agent.loop import run_agent
from shdpa.eval.baselines import b0_restart, b1_rules, b2_single_llm
from shdpa.eval.fixture import load_fixture
from shdpa.eval.metrics import IncidentScore, aggregate, score_incident
from shdpa.models import Incident

POLICIES: dict[str, Callable[[Incident], Incident]] = {
    "b0": b0_restart.run,
    "b1": b1_rules.run,
    "b2": b2_single_llm.run,
    "ours": run_agent,
}


def discover_fixtures(root: Path) -> list[Path]:
    return sorted(p.parent for p in root.rglob("fixture.yaml"))


def run_policy(policy_name: str, fix_dirs: list[Path]) -> list[IncidentScore]:
    """Run one policy across all fixtures.

    Each invocation gets a fresh copy of the fixture repo in a tmpdir so
    that mutations (commits, branch creation, file rewrites) from one
    fixture or policy cannot leak into subsequent runs. The tmpdir is
    deleted as soon as scoring is done — fixtures stay pristine.
    """
    fn = POLICIES[policy_name]
    scores: list[IncidentScore] = []
    for d in fix_dirs:
        incident = load_fixture(d)
        # isolate: copy the repo into a tmpdir so the policy can mutate freely
        # without contaminating the on-disk fixture or other runs.
        with tempfile.TemporaryDirectory(prefix="shdpa-eval-") as tmp:
            if incident.repo_path and Path(incident.repo_path).exists():
                isolated = Path(tmp) / "repo"
                shutil.copytree(incident.repo_path, isolated)
                incident.repo_path = str(isolated)
            incident = fn(copy.deepcopy(incident))
            scores.append(score_incident(incident))
    return scores


def render_table(results: dict[str, list[IncidentScore]]) -> None:
    console = Console()
    t = Table(title="Eval results")
    t.add_column("Policy")
    t.add_column("N", justify="right")
    t.add_column("Resolution", justify="right")
    t.add_column("Class Acc", justify="right")
    t.add_column("Fix-kind Acc", justify="right")
    t.add_column("Macro F1", justify="right")
    t.add_column("MTTR (s)", justify="right")
    t.add_column("$/incident", justify="right")
    t.add_column("Halluc.", justify="right")
    for name, scores in results.items():
        a = aggregate(scores)
        t.add_row(
            name,
            str(a.n),
            f"{a.resolution_rate:.2%}",
            f"{a.class_accuracy:.2%}",
            f"{a.fix_kind_accuracy:.2%}",
            f"{a.macro_f1:.2f}",
            f"{a.mttr_s:.2f}",
            f"${a.cost_per_incident_usd:.4f}",
            f"{a.hallucination_rate:.2%}",
        )
    console.print(t)


def render_per_class(results: dict[str, list[IncidentScore]]) -> None:
    console = Console()
    if "ours" not in results:
        return
    a = aggregate(results["ours"])
    if not a.per_class:
        return
    t = Table(title="Per-class breakdown (policy=ours)")
    t.add_column("Class")
    t.add_column("N", justify="right")
    t.add_column("Resolution", justify="right")
    t.add_column("Class Acc", justify="right")
    for cls, row in sorted(a.per_class.items()):
        t.add_row(cls, str(int(row["n"])),
                  f"{row['resolution_rate']:.2%}",
                  f"{row['class_accuracy']:.2%}")
    console.print(t)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    ap.add_argument("--policy", default="b0,b1,b2,ours",
                    help="comma-separated subset of: b0,b1,b2,ours")
    ap.add_argument("--out", type=Path, default=Path("results.jsonl"))
    args = ap.parse_args(argv)

    fix_dirs = discover_fixtures(args.fixtures)
    if not fix_dirs:
        print(f"no fixtures found under {args.fixtures}", file=sys.stderr)
        return 2
    print(f"found {len(fix_dirs)} fixtures")

    results: dict[str, list[IncidentScore]] = {}
    for p in args.policy.split(","):
        p = p.strip()
        if p not in POLICIES:
            print(f"unknown policy: {p}", file=sys.stderr)
            return 2
        print(f"running policy={p} on {len(fix_dirs)} fixtures...")
        results[p] = run_policy(p, fix_dirs)

    render_table(results)
    render_per_class(results)

    # write JSONL
    with args.out.open("w") as f:
        for policy, scores in results.items():
            for s in scores:
                f.write(json.dumps({"policy": policy, **s.__dict__}) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
