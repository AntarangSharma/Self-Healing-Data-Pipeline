"""Guardrails enforced as code, not as prompt instructions.

Why: the model will violate guardrails encoded only in the system prompt
~5% of the time. Encoding them in middleware that runs after every action
proposal makes them structurally impossible to bypass.
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

from shdpa.models import Action, FailureClass, Incident

# Classes that may be auto-executed without a human-approved PR.
AUTO_FIX_WHITELIST: set[FailureClass] = {
    "schema_drift",   # rename only — still opens PR, never auto-merges
    "upstream_5xx",
    "late_partition",
    "dag_import",
    "disk_full",
}

DESTRUCTIVE_KEYWORDS = (
    "drop table", "drop schema", "truncate", "delete from",
    "rm -rf", "shutdown", "format ", "dropdatabase",
)


class GuardrailViolation(RuntimeError):
    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"[{rule}] {detail}")
        self.rule = rule
        self.detail = detail


@dataclass
class Guardrails:
    max_files_touched: int = 3
    max_lines_changed: int = 80
    forbidden_paths: tuple[str, ...] = (
        "infra/**", "**/prod_*.yml", "**/prod_*.yaml", ".github/**", "secrets/**",
    )
    require_dry_run: bool = field(
        default_factory=lambda: os.getenv("SHDPA_DRY_RUN", "true").lower() == "true"
    )

    def check_repo_allowed(self, incident: Incident) -> None:
        """Reject incidents whose `repo_path` isn't in the allow-list.

        Controlled by env var `SHDPA_ALLOWED_REPOS` — a colon-separated list
        of glob patterns matched against the incident's `repo_path`.

        Default (env unset) is permissive so the existing 27 unit tests and
        the eval harness keep running unchanged. Set the env var in
        production to lock the agent to a known set of repos and prevent
        a poisoned `incident.json` from making the agent touch `/etc/`
        or a sibling repo it has no business in.
        """
        raw = os.getenv("SHDPA_ALLOWED_REPOS", "").strip()
        if not raw:
            return
        if not incident.repo_path:
            raise GuardrailViolation(
                "repo_not_allowed",
                "incident has no repo_path but SHDPA_ALLOWED_REPOS is set",
            )
        resolved = str(Path(incident.repo_path).resolve())
        patterns = [p.strip() for p in raw.split(":") if p.strip()]
        for pat in patterns:
            if fnmatch.fnmatch(resolved, pat) or fnmatch.fnmatch(incident.repo_path, pat):
                return
        raise GuardrailViolation(
            "repo_not_allowed",
            f"{incident.repo_path!r} not in SHDPA_ALLOWED_REPOS={patterns}",
        )

    def check_action(
        self,
        action: Action,
        *,
        predicted_class: FailureClass | None,
        confidence: float,
        diff: str | None,
        files_changed: list[str],
    ) -> None:
        """Raise GuardrailViolation if the action is disallowed."""
        # 1) Forbidden paths
        for path in files_changed:
            for pat in self.forbidden_paths:
                if fnmatch.fnmatch(path, pat):
                    raise GuardrailViolation("forbidden_path", f"{path} matches {pat}")

        # 2) Blast radius
        if len(files_changed) > self.max_files_touched:
            raise GuardrailViolation(
                "blast_radius_files",
                f"{len(files_changed)} files > cap {self.max_files_touched}",
            )
        if diff:
            n_lines = sum(
                1 for line in diff.splitlines()
                if (line.startswith("+") or line.startswith("-"))
                and not line.startswith(("+++", "---"))
            )
            if n_lines > self.max_lines_changed:
                raise GuardrailViolation(
                    "blast_radius_lines",
                    f"{n_lines} lines > cap {self.max_lines_changed}",
                )

        # 3) Destructive content
        body = (diff or "").lower()
        for kw in DESTRUCTIVE_KEYWORDS:
            if kw in body:
                raise GuardrailViolation(
                    "destructive_op",
                    f"diff contains {kw!r}; requires human approval",
                )

        # 4) Auto-execute gate
        if action.kind not in ("pr", "noop", "slack"):
            if predicted_class not in AUTO_FIX_WHITELIST:
                raise GuardrailViolation(
                    "non_whitelisted_class",
                    f"{predicted_class} not in auto-fix whitelist",
                )
            if confidence < 0.85:
                raise GuardrailViolation(
                    "low_confidence",
                    f"confidence {confidence:.2f} < 0.85",
                )
