"""Unit tests for src/resource/base_openai.py."""

import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError

from src.resource.base_openai import BaseAgent


class TestBaseAgentInstantiation:
    """Tests for BaseAgent field validation."""

    def test_creates_with_name_and_instructions(self):
        """Valid name and instructions produce a correctly populated instance."""
        agent = BaseAgent(name="Test Agent", instructions="Do something")
        assert agent.name == "Test Agent"
        assert agent.instructions == "Do something"

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
    """Tests for BaseAgent.run() — the OpenAI Agent/Runner SDK is mocked."""

    @patch("src.resource.base_openai.Agent")
    @patch("src.resource.base_openai.Runner")
    def test_run_creates_agent_with_correct_name_and_instructions(
        self, mock_runner, mock_agent_cls
    ):
        """Agent must be constructed with the instance's name, instructions, and model."""
        mock_runner.run_sync.return_value = MagicMock(final_output="output")

        agent = BaseAgent(name="My Agent", instructions="My instructions")
        agent.run("some message")

        mock_agent_cls.assert_called_once_with(
            name="My Agent", instructions="My instructions", model="gpt-4o"
        )

    @patch("src.resource.base_openai.Agent")
    @patch("src.resource.base_openai.Runner")
    def test_run_passes_agent_instance_and_message_to_runner(
        self, mock_runner, mock_agent_cls
    ):
        """Runner.run_sync must receive the constructed agent and the input message."""
        mock_agent_instance = MagicMock()
        mock_agent_cls.return_value = mock_agent_instance
        mock_runner.run_sync.return_value = MagicMock(final_output="output")

        agent = BaseAgent(name="Agent", instructions="Instructions")
        agent.run("test message")

        mock_runner.run_sync.assert_called_once_with(mock_agent_instance, "test message")

    @patch("src.resource.base_openai.Agent")
    @patch("src.resource.base_openai.Runner")
    def test_run_returns_final_output(self, mock_runner, mock_agent_cls):
        """run() must return Runner.run_sync's final_output value."""
        mock_runner.run_sync.return_value = MagicMock(final_output="Expected response")

        agent = BaseAgent(name="Agent", instructions="Instructions")
        result = agent.run("some input")

        assert result == "Expected response"
