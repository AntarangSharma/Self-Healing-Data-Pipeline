import json
import os
from unittest.mock import MagicMock, patch
import pytest

from shdpa.middleware.secrets import get_secret, _SECRETS_CACHE


@pytest.fixture(autouse=True)
def clear_cache():
    _SECRETS_CACHE.clear()


def test_local_env_fallback():
    with patch.dict(os.environ, {"MY_TEST_SECRET": "local_val"}):
        assert get_secret("MY_TEST_SECRET") == "local_val"
        # Verify it did not cache local env
        assert "MY_TEST_SECRET" not in _SECRETS_CACHE


def test_cache_priority():
    _SECRETS_CACHE["MY_TEST_SECRET"] = "cached_val"
    with patch.dict(os.environ, {"MY_TEST_SECRET": "local_val"}):
        assert get_secret("MY_TEST_SECRET") == "cached_val"


def test_vault_kv_v1():
    vault_response = {
        "data": {
            "MY_VAULT_SECRET": "vault_val_v1"
        }
    }

    with patch.dict(os.environ, {
        "VAULT_ADDR": "http://vault.local",
        "SHDPA_VAULT_PATH": "secret/data/shdpa",
        "VAULT_TOKEN": "token123"
    }, clear=True):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(vault_response).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            val = get_secret("MY_VAULT_SECRET")
            assert val == "vault_val_v1"


def test_vault_kv_v2():
    vault_response = {
        "data": {
            "data": {
                "MY_VAULT_SECRET": "vault_val_v2"
            }
        }
    }

    with patch.dict(os.environ, {
        "VAULT_ADDR": "http://vault.local",
        "SHDPA_VAULT_PATH": "secret/data/shdpa",
        "VAULT_TOKEN": "token123"
    }, clear=True):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(vault_response).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            val = get_secret("MY_VAULT_SECRET")
            assert val == "vault_val_v2"


def test_aws_secrets_manager():
    aws_response = {
        "SecretString": json.dumps({"MY_AWS_SECRET": "aws_val"})
    }

    import sys
    mock_boto3 = MagicMock()
    sys.modules["boto3"] = mock_boto3

    with patch.dict(os.environ, {
        "SHDPA_AWS_SECRET_ID": "arn:aws:secretsmanager:..."
    }, clear=True):
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = aws_response
        mock_boto3.client.return_value = mock_client

        val = get_secret("MY_AWS_SECRET")
        assert val == "aws_val"
