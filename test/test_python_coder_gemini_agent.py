"""Unit tests for src/app/agents/python_coder_gemini_agent.py."""

import unittest
from unittest.mock import patch, MagicMock

from src.ai.base_gemini import BaseAgent as GeminiBaseAgent
from src.app.agents.python_coder_gemini_agent import PythonCoderGeminiAgent

_EXPECTED_INSTRUCTIONS = (
    "You are a professional Python coder. "
    "Write clean, efficient, and well-documented Python code."
)


class TestPythonCoderGeminiAgentDefaults(unittest.TestCase):
    """Tests for PythonCoderGeminiAgent default field values."""

    def test_default_name(self) -> None:
        """Default name is 'Professional Python coder' when not overridden."""
        assert PythonCoderGeminiAgent().name == "Professional Python coder"

    def test_default_instructions(self) -> None:
        """Default instructions match the expected professional-coder persona."""
        assert PythonCoderGeminiAgent().instructions == _EXPECTED_INSTRUCTIONS

    def test_default_model_is_gemini_flash(self) -> None:
        """Default model is gemini-2.0-flash when not overridden."""
        assert PythonCoderGeminiAgent().model == "gemini-2.0-flash"


class TestPythonCoderGeminiAgentOverrides(unittest.TestCase):
    """Tests for overriding PythonCoderGeminiAgent constructor fields."""

    def test_can_override_name(self) -> None:
        """A custom name is stored unchanged on the instance."""
        agent = PythonCoderGeminiAgent(name="Custom Coder")
        assert agent.name == "Custom Coder"

    def test_can_override_instructions(self) -> None:
        """Custom instructions are stored unchanged on the instance."""
        agent = PythonCoderGeminiAgent(instructions="Only write async code")
        assert agent.instructions == "Only write async code"

    def test_can_override_model(self) -> None:
        """A custom model string is stored unchanged on the instance."""
        agent = PythonCoderGeminiAgent(model="gemini-1.5-pro")
        assert agent.model == "gemini-1.5-pro"


class TestPythonCoderGeminiAgentRun(unittest.TestCase):
    """Tests for PythonCoderGeminiAgent.run() with a mocked genai backend."""

    def _make_mock_genai(self, text: str = "output") -> MagicMock:
        """Build a genai mock wired for the start_chat / send_message API.

        Args:
            text: Text to embed in the mocked response.

        Returns:
            MagicMock: A mock genai module returning the given response text.
        """
        mock_genai = MagicMock()
        mock_model_instance = MagicMock()
        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.text = text
        mock_response.candidates = []          # no function-call parts
        mock_chat.send_message.return_value = mock_response
        mock_model_instance.start_chat.return_value = mock_chat
        mock_genai.GenerativeModel.return_value = mock_model_instance
        return mock_genai

    @patch("src.ai.base_gemini.genai")
    def test_run_delegates_to_base(self, mock_genai: MagicMock) -> None:
        """run() must forward the message unchanged to send_message."""
        wired = self._make_mock_genai("def hello(): print('hello world')")
        mock_genai.GenerativeModel.return_value = wired.GenerativeModel.return_value

        agent = PythonCoderGeminiAgent()
        agent.run("write hello world")

        mock_chat = mock_genai.GenerativeModel.return_value.start_chat.return_value
        mock_chat.send_message.assert_called_once_with("write hello world")

    @patch("src.ai.base_gemini.genai")
    def test_run_returns_response_text(self, mock_genai: MagicMock) -> None:
        """run() must return the mocked response's text attribute."""
        wired = self._make_mock_genai("def hello(): print('hello world')")
        mock_genai.GenerativeModel.return_value = wired.GenerativeModel.return_value

        result = PythonCoderGeminiAgent().run("write hello world")

        assert result == "def hello(): print('hello world')"

    @patch("src.ai.base_gemini.genai")
    def test_run_configures_genai_with_api_key(self, mock_genai: MagicMock) -> None:
        """genai.configure must be called once with an api_key kwarg."""
        wired = self._make_mock_genai("ok")
        mock_genai.GenerativeModel.return_value = wired.GenerativeModel.return_value

        PythonCoderGeminiAgent().run("ping")

        mock_genai.configure.assert_called_once()
        _, kwargs = mock_genai.configure.call_args
        assert "api_key" in kwargs

    @patch("src.ai.base_gemini.genai")
    def test_run_builds_model_with_correct_system_instruction(
        self, mock_genai: MagicMock
    ) -> None:
        """GenerativeModel must be built with the agent's model and instructions."""
        wired = self._make_mock_genai("ok")
        mock_genai.GenerativeModel.return_value = wired.GenerativeModel.return_value

        agent = PythonCoderGeminiAgent()
        agent.run("ping")

        mock_genai.GenerativeModel.assert_called_once_with(
            model_name=agent.model,
            system_instruction=agent.instructions,
        )


class TestPythonCoderGeminiAgentInheritance(unittest.TestCase):
    """Tests for PythonCoderGeminiAgent's class hierarchy."""

    def test_inherits_from_gemini_base_agent(self) -> None:
        """PythonCoderGeminiAgent must subclass the Gemini BaseAgent."""
        assert issubclass(PythonCoderGeminiAgent, GeminiBaseAgent)

    def test_instantiates_without_arguments(self) -> None:
        """Agent can be constructed with no arguments."""
        agent = PythonCoderGeminiAgent()
        assert agent is not None


if __name__ == "__main__":
    unittest.main()
