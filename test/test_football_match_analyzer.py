"""Unit tests for src/app/agents/football_match_analyzer.py."""

from unittest.mock import patch, MagicMock

from src.resource.base_openai import BaseAgent as OpenAIBaseAgent
from src.app.agents.football_match_analyzer import FootballMatchAnalyzerAgent


class TestFootballMatchAnalyzerDefaults:
    """Tests for FootballMatchAnalyzerAgent default field values."""

    def test_default_name(self):
        """Default name is 'Football match analyzer' when not overridden."""
        assert FootballMatchAnalyzerAgent().name == "Football match analyzer"

    def test_default_instructions_mention_football(self):
        """Default instructions must reference football."""
        assert "football" in FootballMatchAnalyzerAgent().instructions.lower()

    def test_instantiates_without_arguments(self):
        """Agent can be constructed with no arguments."""
        agent = FootballMatchAnalyzerAgent()
        assert agent is not None

    def test_inherits_from_openai_base_agent(self):
        """FootballMatchAnalyzerAgent must subclass the OpenAI BaseAgent."""
        assert issubclass(FootballMatchAnalyzerAgent, OpenAIBaseAgent)


class TestFootballMatchAnalyzerOverrides:
    """Tests for overriding FootballMatchAnalyzerAgent constructor fields."""

    def test_name_can_be_overridden(self):
        """A custom name is stored unchanged on the instance."""
        agent = FootballMatchAnalyzerAgent(name="Sports Analyst")
        assert agent.name == "Sports Analyst"

    def test_instructions_can_be_overridden(self):
        """Custom instructions are stored unchanged on the instance."""
        agent = FootballMatchAnalyzerAgent(instructions="Focus on statistics only")
        assert agent.instructions == "Focus on statistics only"


class TestFootballMatchAnalyzerRun:
    """Tests for FootballMatchAnalyzerAgent.run() with a mocked OpenAI backend."""

    @patch("src.resource.base_openai.Agent")
    @patch("src.resource.base_openai.Runner")
    def test_run_returns_backend_output(self, mock_runner, mock_agent_cls):
        """run() must return the Runner's final_output value."""
        mock_runner.run_sync.return_value = MagicMock(final_output="Match analysis result")

        result = FootballMatchAnalyzerAgent().run("Analyze Liverpool vs Arsenal")

        assert result == "Match analysis result"

    @patch("src.resource.base_openai.Agent")
    @patch("src.resource.base_openai.Runner")
    def test_run_forwards_message_to_runner(self, mock_runner, mock_agent_cls):
        """The input message must be forwarded unchanged to Runner.run_sync."""
        mock_runner.run_sync.return_value = MagicMock(final_output="output")

        FootballMatchAnalyzerAgent().run("Who won El Clasico?")

        _, call_args, _ = mock_runner.run_sync.mock_calls[0]
        assert call_args[1] == "Who won El Clasico?"
