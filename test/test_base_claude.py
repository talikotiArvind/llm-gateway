"""Unit tests for src/resource/base_claude.py."""

import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError

from src.resource.base_claude import BaseAgent


class TestBaseAgentInstantiation:
    """Tests for BaseAgent field validation and default values."""

    def test_creates_with_name_and_instructions(self):
        """Valid name and instructions produce a correctly populated instance."""
        agent = BaseAgent(name="Test Agent", instructions="Do something")
        assert agent.name == "Test Agent"
        assert agent.instructions == "Do something"

    def test_default_model_is_claude_sonnet(self):
        """Default model is claude-sonnet-4-6 when no model is supplied."""
        agent = BaseAgent(name="Test", instructions="Test")
        assert agent.model == "claude-sonnet-4-6"

    def test_model_can_be_overridden(self):
        """A custom model string is stored unchanged on the instance."""
        agent = BaseAgent(name="Test", instructions="Test", model="claude-opus-4-6")
        assert agent.model == "claude-opus-4-6"

    def test_missing_name_raises_validation_error(self):
        """Omitting `name` must raise a pydantic ValidationError."""
        with pytest.raises(ValidationError):
            BaseAgent(instructions="Some instructions")

    def test_missing_instructions_raises_validation_error(self):
        """Omitting `instructions` must raise a pydantic ValidationError."""
        with pytest.raises(ValidationError):
            BaseAgent(name="Some name")

    def test_missing_both_fields_raises_validation_error(self):
        """Omitting both required fields must raise a pydantic ValidationError."""
        with pytest.raises(ValidationError):
            BaseAgent()


class TestBaseAgentRun:
    """Tests for BaseAgent.run() — all external Anthropic calls are mocked."""

    def _make_mock_client(self, text="response"):
        """Build a mock Anthropic client whose messages.create() returns given text.

        Args:
            text: Text to embed in the mocked response content.

        Returns:
            MagicMock: A mock Anthropic client wired to return a response.
        """
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=text)]
        mock_client.messages.create.return_value = mock_response
        return mock_client

    @patch("src.resource.base_claude.Anthropic")
    def test_run_creates_anthropic_client_with_api_key(self, mock_anthropic_cls):
        """Anthropic client must be instantiated once with an api_key kwarg."""
        mock_anthropic_cls.return_value = self._make_mock_client()

        agent = BaseAgent(name="Test", instructions="Test")
        agent.run("hello")

        mock_anthropic_cls.assert_called_once()
        assert "api_key" in mock_anthropic_cls.call_args.kwargs

    @patch("src.resource.base_claude.Anthropic")
    def test_run_calls_messages_create_with_correct_params(self, mock_anthropic_cls):
        """messages.create() must receive model, max_tokens, system, and messages."""
        mock_client = self._make_mock_client()
        mock_anthropic_cls.return_value = mock_client

        agent = BaseAgent(name="Test", instructions="System prompt", model="claude-sonnet-4-6")
        agent.run("User message")

        mock_client.messages.create.assert_called_once_with(
            model="claude-sonnet-4-6",
            max_tokens=8096,
            system="System prompt",
            messages=[{"role": "user", "content": "User message"}],
        )

    @patch("src.resource.base_claude.Anthropic")
    def test_run_uses_overridden_model(self, mock_anthropic_cls):
        """When a custom model is set, messages.create() must receive that model."""
        mock_client = self._make_mock_client()
        mock_anthropic_cls.return_value = mock_client

        agent = BaseAgent(name="Test", instructions="Test", model="claude-opus-4-6")
        agent.run("question")

        _, kwargs = mock_client.messages.create.call_args
        assert kwargs["model"] == "claude-opus-4-6"

    @patch("src.resource.base_claude.Anthropic")
    def test_run_returns_first_content_text(self, mock_anthropic_cls):
        """run() must return the text of the first content block in the response."""
        mock_client = self._make_mock_client(text="Claude's response")
        mock_anthropic_cls.return_value = mock_client

        agent = BaseAgent(name="Test", instructions="Test")
        result = agent.run("question")

        assert result == "Claude's response"
