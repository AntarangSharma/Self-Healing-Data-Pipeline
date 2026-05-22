"""PII / secret redaction.

Why: an Airflow log can contain anything — API keys, JWTs, customer PII,
S3 URLs with credentials. Without this middleware those bytes get shipped
verbatim to the LLM provider. That's both a legal risk (GDPR, SOC 2) and a
security risk (cached completions on the provider side).

The redactor runs BEFORE any LLM call. It is deliberately over-aggressive:
false positives mean "the LLM sees `<REDACTED:api_key>` instead of the real
key" which is fine; false negatives mean "the key leaks" which is not.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

# Each pattern is (label, compiled_regex). Order matters — more specific
# patterns first so a generic "looks like a token" rule doesn't eat a
# specific provider key.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Cloud provider API keys
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_key", re.compile(r"\b[A-Za-z0-9/+=]{40}\b(?=.*aws)", re.IGNORECASE)),
    ("gcp_service_account", re.compile(r"-----BEGIN PRIVATE KEY-----[\s\S]+?-----END PRIVATE KEY-----")),
    # LLM provider keys (anthropic FIRST — its prefix sk-ant- also matches
    # the openai pattern, so we must redact it under the right label)
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    # GitHub
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github_oauth", re.compile(r"\b[0-9a-f]{40}\b(?=.*github)", re.IGNORECASE)),
    # Generic high-entropy bearer tokens
    ("bearer_token", re.compile(
        r"(?i)(?:bearer|authorization:\s*bearer)\s+([A-Za-z0-9._\-+/=]{20,})"
    )),
    # JWTs
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    # SSH private keys
    ("ssh_private_key", re.compile(
        r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----[\s\S]+?"
        r"-----END (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"
    )),
    # Database URLs with embedded passwords:  postgres://user:pass@host/db
    ("db_url_with_password", re.compile(
        r"\b(?:postgres|postgresql|mysql|mongodb|redis)(?:\+\w+)?://"
        r"[^:\s/]+:[^@\s]+@[^\s'\"]+"
    )),
    # Email addresses
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # Credit cards (very loose — 13-19 digits with optional spaces/dashes)
    ("credit_card", re.compile(r"\b(?:\d[ \-]*?){13,19}\b")),
    # IPv4 addresses (often internal infra; usually OK to redact)
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


@dataclass
class RedactionReport:
    text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def redact(text: str, *, skip_labels: tuple[str, ...] = ()) -> RedactionReport:
    """Replace secrets/PII with `<REDACTED:label>` placeholders.

    Args:
        text: input string (e.g. an Airflow log).
        skip_labels: labels to NOT redact. Useful if you genuinely need
            emails in the log to debug something — pass `skip_labels=("email",)`.

    Returns:
        RedactionReport with the cleaned text and per-label counts.
    """
    counts: dict[str, int] = {}
    out = text
    for label, pat in _PATTERNS:
        if label in skip_labels:
            continue
        new, n = pat.subn(f"<REDACTED:{label}>", out)
        if n:
            counts[label] = n
            out = new
    return RedactionReport(text=out, counts=counts)


def redact_incident_in_place(incident_log: str) -> tuple[str, dict[str, int]]:
    """Convenience wrapper for the agent loop.

    Honors SHDPA_DISABLE_REDACTION=1 for the rare cases where redaction
    is provably unnecessary (e.g. running entirely against synthetic
    fixtures in CI). Default: redaction ON.
    """
    if os.getenv("SHDPA_DISABLE_REDACTION", "0") == "1":
        return incident_log, {}
    rep = redact(incident_log)
    return rep.text, rep.counts
