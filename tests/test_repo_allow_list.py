"""Tests for the per-repo allow-list guardrail."""
from __future__ import annotations

from pathlib import Path

import pytest

from shdpa.agent.guardrails import Guardrails, GuardrailViolation
from shdpa.models import Incident


def test_unset_env_is_permissive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHDPA_ALLOWED_REPOS", raising=False)
    g = Guardrails()
    g.check_repo_allowed(Incident(repo_path="/anywhere/at/all"))  # no raise


def test_matching_glob_allowed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    monkeypatch.setenv("SHDPA_ALLOWED_REPOS", f"{tmp_path}/*")
    g = Guardrails()
    g.check_repo_allowed(Incident(repo_path=str(tmp_path / "repo")))  # no raise


def test_non_matching_glob_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("SHDPA_ALLOWED_REPOS", "/srv/airflow/*")
    g = Guardrails()
    with pytest.raises(GuardrailViolation) as exc:
        g.check_repo_allowed(Incident(repo_path=str(tmp_path / "evil")))
    assert exc.value.rule == "repo_not_allowed"


def test_missing_repo_path_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHDPA_ALLOWED_REPOS", "/srv/*")
    g = Guardrails()
    with pytest.raises(GuardrailViolation):
        g.check_repo_allowed(Incident(repo_path=""))


def test_multiple_globs_colon_separated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    monkeypatch.setenv(
        "SHDPA_ALLOWED_REPOS",
        f"{tmp_path}/a:{tmp_path}/b",
    )
    g = Guardrails()
    g.check_repo_allowed(Incident(repo_path=str(tmp_path / "a")))
    g.check_repo_allowed(Incident(repo_path=str(tmp_path / "b")))
    with pytest.raises(GuardrailViolation):
        g.check_repo_allowed(Incident(repo_path=str(tmp_path / "c")))
