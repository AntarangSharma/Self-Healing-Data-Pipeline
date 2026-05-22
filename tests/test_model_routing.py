import sys
from unittest.mock import MagicMock

# Pre-emptively mock the external provider libraries so importing the providers succeeds
sys.modules["openai"] = MagicMock()
sys.modules["anthropic"] = MagicMock()

import os
from unittest.mock import patch
import pytest

from shdpa.llm.openai_provider import OpenAIProvider
from shdpa.llm.anthropic_provider import AnthropicProvider


def test_openai_model_routing():
    with patch("shdpa.middleware.secrets.get_secret", return_value="fake-key"):
        provider = OpenAIProvider()

        # Mock client chat.completions.create
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "response content"
        mock_completion.usage = MagicMock()
        mock_completion.usage.prompt_tokens = 10
        mock_completion.usage.completion_tokens = 5
        provider.client.chat.completions.create.return_value = mock_completion

        # Test triage purpose
        resp = provider.complete("sys", "usr", purpose="triage")
        assert resp.model == "gpt-4o-mini"
        provider.client.chat.completions.create.assert_called_with(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
            max_tokens=1024,
            temperature=0.1
        )

        # Test diagnose purpose
        resp2 = provider.complete("sys", "usr", purpose="diagnose")
        assert resp2.model == "gpt-4o"
        provider.client.chat.completions.create.assert_called_with(
            model="gpt-4o",
            messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
            max_tokens=1024,
            temperature=0.1
        )


def test_anthropic_model_routing():
    with patch("shdpa.middleware.secrets.get_secret", return_value="fake-key"):
        provider = AnthropicProvider()

        # Mock client messages.create
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "response content"
        mock_msg.content = [mock_block]
        mock_msg.usage = MagicMock()
        mock_msg.usage.input_tokens = 10
        mock_msg.usage.output_tokens = 5
        provider.client.messages.create.return_value = mock_msg

        # Test triage purpose
        resp = provider.complete("sys", "usr", purpose="triage")
        assert resp.model == "claude-3-5-haiku-latest"
        provider.client.messages.create.assert_called_with(
            model="claude-3-5-haiku-latest",
            system="sys",
            messages=[{"role": "user", "content": "usr"}],
            max_tokens=1024,
            temperature=0.1
        )

        # Test diagnose purpose
        resp2 = provider.complete("sys", "usr", purpose="diagnose")
        assert resp2.model == "claude-3-5-sonnet-latest"
        provider.client.messages.create.assert_called_with(
            model="claude-3-5-sonnet-latest",
            system="sys",
            messages=[{"role": "user", "content": "usr"}],
            max_tokens=1024,
            temperature=0.1
        )
