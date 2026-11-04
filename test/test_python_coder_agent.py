"""Unit tests for src/app/agents/python_coder_agent.py."""

from unittest.mock import patch, MagicMock

from src.ai.base_openai import BaseAgent as OpenAIBaseAgent
from src.app.agents.python_coder_agent import PythonCoderAgent


class TestPythonCoderAgentDefaults:
    """Tests for PythonCoderAgent default field values."""

    def test_default_name(self):
        """Default name is 'Professional Python coder' when not overridden."""
        assert PythonCoderAgent().name == "Professional Python coder"

    def test_default_instructions_mention_python(self):
        """Default instructions must reference Python."""
        assert "Python" in PythonCoderAgent().instructions

    def test_instantiates_without_arguments(self):
        """Agent can be constructed with no arguments."""
        agent = PythonCoderAgent()
        assert agent is not None

    def test_inherits_from_openai_base_agent(self):
        """PythonCoderAgent must subclass the OpenAI BaseAgent."""
        assert issubclass(PythonCoderAgent, OpenAIBaseAgent)


class TestPythonCoderAgentOverrides:
    """Tests for overriding PythonCoderAgent constructor fields."""

    def test_name_can_be_overridden(self):
        """A custom name is stored unchanged on the instance."""
        agent = PythonCoderAgent(name="Custom Name")
        assert agent.name == "Custom Name"

    def test_instructions_can_be_overridden(self):
        """Custom instructions are stored unchanged on the instance."""
        agent = PythonCoderAgent(instructions="Only write async code")
        assert agent.instructions == "Only write async code"


class TestPythonCoderAgentRun:
    """Tests for PythonCoderAgent.run() with a mocked OpenAI backend."""

    @patch("src.ai.base_openai.Agent")
    @patch("src.ai.base_openai.Runner")
    def test_run_returns_backend_output(self, mock_runner, mock_agent_cls):
        """run() must return the Runner's final_output value."""
        mock_runner.run_sync.return_value = MagicMock(final_output="print('hello')")

        result = PythonCoderAgent().run("Write hello world")

        assert result == "print('hello')"

    @patch("src.ai.base_openai.Agent")
    @patch("src.ai.base_openai.Runner")
    def test_run_forwards_message_to_runner(self, mock_runner, mock_agent_cls):
        """The input message must be forwarded unchanged to Runner.run_sync."""
        mock_runner.run_sync.return_value = MagicMock(final_output="output")

        PythonCoderAgent().run("Sort a list")

        _, call_args, _ = mock_runner.run_sync.mock_calls[0]
        assert call_args[1] == "Sort a list"
