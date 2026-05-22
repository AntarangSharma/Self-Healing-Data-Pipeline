"""Tests for the PII / secret redaction middleware."""

from __future__ import annotations

import pytest

from shdpa.middleware.redact import redact, redact_incident_in_place


@pytest.mark.parametrize(
    "dirty,label",
    [
        ("aws key AKIAABCDEFGHIJKLMNOP rest", "aws_access_key"),
        ("Authorization: Bearer abcdef1234567890ABCDEF==", "bearer_token"),
        ("token sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxx end", "anthropic_key"),
        ("openai key sk-proj-AABBCCDDEEFFGGHHIIJJ rest", "openai_key"),
        ("gh token ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA end", "github_token"),
        ("jwt eyJhbGciOiJI.eyJzdWIiOiJ1MjMifQ.aBcDef123 end", "jwt"),
        ("conn postgres://alice:hunter2@db.internal:5432/prod end", "db_url_with_password"),
        ("email contact me at alice@example.com please", "email"),
        ("ip 10.0.0.5 is down", "ipv4"),
    ],
)
def test_pattern_detected(dirty: str, label: str) -> None:
    rep = redact(dirty)
    assert f"<REDACTED:{label}>" in rep.text, (
        f"label {label} not matched in {dirty!r}; got {rep.text!r}"
    )
    assert rep.counts.get(label, 0) >= 1


def test_clean_text_passes_through() -> None:
    txt = "ValueError: column o_customerkey not found in table orders"
    rep = redact(txt)
    assert rep.text == txt
    assert rep.counts == {}


def test_multiple_secrets_same_text() -> None:
    txt = "AKIAABCDEFGHIJKLMNOP and AKIAZZZZZZZZZZZZZZZZ on host 1.2.3.4"
    rep = redact(txt)
    assert rep.counts["aws_access_key"] == 2
    assert rep.counts["ipv4"] == 1
    assert "AKIA" not in rep.text


def test_skip_labels_keeps_emails() -> None:
    txt = "page alice@example.com about AKIAABCDEFGHIJKLMNOP"
    rep = redact(txt, skip_labels=("email",))
    assert "alice@example.com" in rep.text
    assert "<REDACTED:aws_access_key>" in rep.text


def test_disable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHDPA_DISABLE_REDACTION", "1")
    txt = "AKIAABCDEFGHIJKLMNOP"
    clean, counts = redact_incident_in_place(txt)
    assert clean == txt
    assert counts == {}


def test_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHDPA_DISABLE_REDACTION", raising=False)
    clean, counts = redact_incident_in_place("Bearer abcdefghijklmnopqrstuvwxyz")
    assert "<REDACTED:bearer_token>" in clean
    assert counts.get("bearer_token", 0) == 1
