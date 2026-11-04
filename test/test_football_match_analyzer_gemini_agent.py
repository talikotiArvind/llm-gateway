"""Unit tests for src/app/agents/football_match_analyzer_gemini_agent.py."""

import unittest
from unittest.mock import patch, MagicMock

from src.resource.base_gemini import BaseAgent as GeminiBaseAgent
from src.app.agents.football_match_analyzer_gemini_agent import FootballMatchAnalyzerGeminiAgent


class TestFootballMatchAnalyzerGeminiAgentInheritance(unittest.TestCase):
    """Tests for FootballMatchAnalyzerGeminiAgent's class hierarchy."""

    def test_inherits_from_gemini_base_agent(self) -> None:
        """FootballMatchAnalyzerGeminiAgent must subclass the Gemini BaseAgent."""
        self.assertTrue(issubclass(FootballMatchAnalyzerGeminiAgent, GeminiBaseAgent))

    def test_instantiates_without_arguments(self) -> None:
        """Agent can be constructed with no arguments."""
        agent = FootballMatchAnalyzerGeminiAgent()
        self.assertIsNotNone(agent)


class TestFootballMatchAnalyzerGeminiAgentDefaults(unittest.TestCase):
    """Tests for FootballMatchAnalyzerGeminiAgent default field values."""

    def test_default_name(self) -> None:
        """Default name is 'Football match analyzer' when not overridden."""
        agent = FootballMatchAnalyzerGeminiAgent()
        self.assertEqual(agent.name, "Football match analyzer")

    def test_default_instructions(self) -> None:
        """Default instructions describe the football-analyst persona."""
        agent = FootballMatchAnalyzerGeminiAgent()
        self.assertEqual(
            agent.instructions,
            "You are a football match analyst. Analyze football matches and provide detailed insights.",
        )

    def test_default_model_is_gemini_flash(self) -> None:
        """Default model is gemini-2.0-flash when not overridden."""
        agent = FootballMatchAnalyzerGeminiAgent()
        self.assertEqual(agent.model, "gemini-2.0-flash")


class TestFootballMatchAnalyzerGeminiAgentOverrides(unittest.TestCase):
    """Tests for overriding FootballMatchAnalyzerGeminiAgent constructor fields."""

    def test_can_override_name(self) -> None:
        """A custom name is stored unchanged on the instance."""
        agent = FootballMatchAnalyzerGeminiAgent(name="Sports Analyst")
        self.assertEqual(agent.name, "Sports Analyst")

    def test_can_override_instructions(self) -> None:
        """Custom instructions are stored unchanged on the instance."""
        agent = FootballMatchAnalyzerGeminiAgent(instructions="Focus on statistics only.")
        self.assertEqual(agent.instructions, "Focus on statistics only.")

    def test_can_override_model(self) -> None:
        """A custom model string is stored unchanged on the instance."""
        agent = FootballMatchAnalyzerGeminiAgent(model="gemini-1.5-pro")
        self.assertEqual(agent.model, "gemini-1.5-pro")


class TestFootballMatchAnalyzerGeminiAgentRun(unittest.TestCase):
    """Tests for FootballMatchAnalyzerGeminiAgent.run() with a mocked genai backend."""

    @patch("src.resource.base_gemini.genai")
    def test_run_delegates_to_base(self, mock_genai: MagicMock) -> None:
        """run() must delegate to the base agent and return the mocked response text."""
        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Match analysis result"
        mock_response.candidates = []          # no function-call parts
        mock_chat.send_message.return_value = mock_response

        mock_model_instance = MagicMock()
        mock_model_instance.start_chat.return_value = mock_chat
        mock_genai.GenerativeModel.return_value = mock_model_instance

        agent = FootballMatchAnalyzerGeminiAgent()
        result = agent.run("analyze Arsenal vs Chelsea")

        mock_chat.send_message.assert_called_once_with("analyze Arsenal vs Chelsea")
        self.assertEqual(result, "Match analysis result")


if __name__ == "__main__":
    unittest.main()
