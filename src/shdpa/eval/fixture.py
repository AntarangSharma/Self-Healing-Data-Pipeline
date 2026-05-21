"""Fixture loader. Reads fixture.yaml + side files into an Incident."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from shdpa.models import GroundTruth, GroundTruthFix, Incident


@dataclass
class FixtureDir:
    path: Path
    meta: dict[str, Any]

    @property
    def id(self) -> str:
        return self.meta["id"]


def load_fixture(fix_dir: Path) -> Incident:
    """Read a fixture directory and produce an Incident populated with inputs + ground truth."""
    meta = yaml.safe_load((fix_dir / "fixture.yaml").read_text())
    inputs = meta["inputs"]
    log_text = (fix_dir / inputs["log_path"]).read_text(encoding="utf-8")
    schema_before = json.loads((fix_dir / inputs["schema_before"]).read_text())
    schema_after = json.loads((fix_dir / inputs["schema_after"]).read_text())
    repo_path = str((fix_dir / inputs["repo_path"]).resolve())

    gt = meta["ground_truth"]
    incident = Incident(
        source="replay",
        dag_id=inputs.get("dag_id", ""),
        task_id=inputs.get("task_id", ""),
        run_id=inputs.get("run_id", ""),
        repo_path=repo_path,
        log_text=log_text,
        schema_before=schema_before,
        schema_after=schema_after,
        exception_type=inputs.get("exception_type"),
        exception_message=inputs.get("exception_message"),
        ground_truth=GroundTruth(
            failure_class=gt["failure_class"],
            root_cause_summary=gt["root_cause_summary"],
            fix=GroundTruthFix(**gt["fix"]),
            severity=gt.get("severity", "P3"),
            auto_fixable=gt.get("auto_fixable", False),
        ),
        fixture_id=meta["id"],
    )
    return incident
