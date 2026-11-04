"""Unit tests for src/app/agents/python_coder_claude_agent.py."""

from unittest.mock import patch, MagicMock

from src.resource.base_claude import BaseAgent as ClaudeBaseAgent
from src.app.agents.python_coder_claude_agent import PythonCoderClaudeAgent


class TestPythonCoderClaudeAgentDefaults:
    """Tests for PythonCoderClaudeAgent default field values."""

    def test_default_name(self):
        """Default name is 'Professional Python coder' when not overridden."""
        assert PythonCoderClaudeAgent().name == "Professional Python coder"

    def test_default_instructions_mention_python(self):
        """Default instructions must reference Python."""
        assert "Python" in PythonCoderClaudeAgent().instructions

    def test_default_model_is_claude_sonnet(self):
        """Default model is claude-sonnet-4-6 when not overridden."""
        assert PythonCoderClaudeAgent().model == "claude-sonnet-4-6"

    def test_instantiates_without_arguments(self):
        """Agent can be constructed with no arguments."""
        agent = PythonCoderClaudeAgent()
        assert agent is not None

    def test_inherits_from_claude_base_agent(self):
        """PythonCoderClaudeAgent must subclass the Claude BaseAgent."""
        assert issubclass(PythonCoderClaudeAgent, ClaudeBaseAgent)


class TestPythonCoderClaudeAgentOverrides:
    """Tests for overriding PythonCoderClaudeAgent constructor fields."""

    def test_instructions_can_be_overridden(self):
        """Custom instructions are stored unchanged on the instance."""
        agent = PythonCoderClaudeAgent(instructions="Only write async code")
        assert agent.instructions == "Only write async code"

    def test_model_can_be_overridden(self):
        """A custom model string is stored unchanged on the instance."""
        agent = PythonCoderClaudeAgent(model="claude-opus-4-6")
        assert agent.model == "claude-opus-4-6"

    def test_name_can_be_overridden(self):
        """A custom name is stored unchanged on the instance."""
        agent = PythonCoderClaudeAgent(name="Custom Coder")
        assert agent.name == "Custom Coder"


class TestPythonCoderClaudeAgentRun:
    """Tests for PythonCoderClaudeAgent.run() with a mocked Anthropic backend."""

    def _make_mock_client(self, text="output"):
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
    def test_run_returns_claude_output(self, mock_anthropic_cls):
        """run() must return the text produced by the mocked Anthropic client."""
        mock_anthropic_cls.return_value = self._make_mock_client("def hello(): pass")

        result = PythonCoderClaudeAgent().run("Write a hello function")

        assert result == "def hello(): pass"

    @patch("src.resource.base_claude.Anthropic")
    def test_run_sends_default_instructions_as_system_prompt(self, mock_anthropic_cls):
        """The agent's instructions must be passed as the system prompt."""
        mock_client = self._make_mock_client()
        mock_anthropic_cls.return_value = mock_client

        agent = PythonCoderClaudeAgent()
        agent.run("Write a sort function")

        _, kwargs = mock_client.messages.create.call_args
        assert kwargs["system"] == agent.instructions

    @patch("src.resource.base_claude.Anthropic")
    def test_run_forwards_message_as_user_content(self, mock_anthropic_cls):
        """The input message must be forwarded as a single user-role message."""
        mock_client = self._make_mock_client()
        mock_anthropic_cls.return_value = mock_client

        PythonCoderClaudeAgent().run("Implement binary search")

        _, kwargs = mock_client.messages.create.call_args
        assert kwargs["messages"] == [{"role": "user", "content": "Implement binary search"}]
