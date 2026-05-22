import os
from unittest.mock import MagicMock, patch
import pytest

from shdpa.llm.provider import get_provider, LLMResponse
from shdpa.llm.failover_provider import FailoverProvider


def test_get_provider_with_failover():
    with patch.dict(os.environ, {"SHDPA_LLM_PROVIDER": "mock", "SHDPA_FALLBACK_PROVIDER": "mock"}):
        provider = get_provider()
        assert isinstance(provider, FailoverProvider)
        assert provider.primary.name == "mock"
        assert provider.fallback.name == "mock"


def test_failover_provider_success():
    primary = MagicMock()
    fallback = MagicMock()

    primary.name = "mock_primary"
    primary.model = "mock_model"
    expected_resp = LLMResponse(
        text="success",
        prompt_tokens=1,
        completion_tokens=1,
        cost_usd=0.01,
        latency_ms=10,
        model="primary-model",
        provider="primary",
    )
    primary.complete.return_value = expected_resp

    provider = FailoverProvider(primary, fallback)
    resp = provider.complete("sys", "usr")

    assert resp == expected_resp
    primary.complete.assert_called_once()
    fallback.complete.assert_not_called()


def test_failover_provider_trigger():
    primary = MagicMock()
    fallback = MagicMock()

    primary.name = "mock_primary"
    primary.model = "mock_model"
    primary.complete.side_effect = RuntimeError("Outage!")

    expected_resp = LLMResponse(
        text="fallback success",
        prompt_tokens=2,
        completion_tokens=2,
        cost_usd=0.02,
        latency_ms=20,
        model="fallback-model",
        provider="fallback",
    )
    fallback.complete.return_value = expected_resp

    provider = FailoverProvider(primary, fallback)
    resp = provider.complete("sys", "usr")

    assert resp == expected_resp
    primary.complete.assert_called_once()
    fallback.complete.assert_called_once()
