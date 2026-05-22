"""Centralized secret management.

Allows retrieving sensitive API keys and connection strings from secure vaults
(HashiCorp Vault or AWS Secrets Manager) if configured, falling back to local
environment variables.
"""

from __future__ import annotations

import json
import os
from typing import Any

import structlog

log = structlog.get_logger()

# In-memory cache for loaded secrets to minimize external provider round-trips.
_SECRETS_CACHE: dict[str, str] = {}


def get_secret(key_name: str, default: str | None = None) -> str | None:
    """Retrieve secret from Vault, AWS Secrets Manager, or local environment fallback.

    Priorities:
    1) Cached secrets from a previous lookup.
    2) HashiCorp Vault (if VAULT_ADDR and SHDPA_VAULT_PATH are configured).
    3) AWS Secrets Manager (if SHDPA_AWS_SECRET_ID or SHDPA_AWS_SECRET_NAME is configured).
    4) Local environment variables.
    """
    if key_name in _SECRETS_CACHE:
        return _SECRETS_CACHE[key_name]

    vault_addr = os.getenv("VAULT_ADDR")
    vault_path = os.getenv("SHDPA_VAULT_PATH")
    aws_secret_id = os.getenv("SHDPA_AWS_SECRET_ID") or os.getenv("SHDPA_AWS_SECRET_NAME")

    # 1) HashiCorp Vault
    if vault_addr and vault_path:
        token = os.getenv("VAULT_TOKEN")
        if not token:
            log.warning(
                "secrets.vault_missing_token", msg="VAULT_ADDR set but VAULT_TOKEN is missing"
            )
        else:
            try:
                import urllib.request
                import urllib.error

                url = f"{vault_addr.rstrip('/')}/v1/{vault_path}"
                req = urllib.request.Request(url, headers={"X-Vault-Token": token})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                    # Vault KV-v2 wraps data inside {"data": {"data": {...}}}
                    # Vault KV-v1 returns data inside {"data": {...}}
                    outer_data = payload.get("data", {})
                    if "data" in outer_data and isinstance(outer_data["data"], dict):
                        secret_dict = outer_data["data"]
                    elif isinstance(outer_data, dict):
                        secret_dict = outer_data
                    else:
                        secret_dict = {}

                    for k, v in secret_dict.items():
                        _SECRETS_CACHE[k] = str(v)
            except Exception as e:
                log.warning("secrets.vault_fetch_failed", error=repr(e))

    # 2) AWS Secrets Manager
    elif aws_secret_id:
        try:
            import boto3

            client = boto3.client("secretsmanager")
            res = client.get_secret_value(SecretId=aws_secret_id)
            if "SecretString" in res:
                secret_dict = json.loads(res["SecretString"])
                if isinstance(secret_dict, dict):
                    for k, v in secret_dict.items():
                        _SECRETS_CACHE[k] = str(v)
        except Exception as e:
            log.warning("secrets.aws_sm_fetch_failed", error=repr(e))

    # Check cache again
    if key_name in _SECRETS_CACHE:
        return _SECRETS_CACHE[key_name]

    # 3) Local environment variable fallback
    val = os.getenv(key_name)
    if val is not None:
        return val

    return default
