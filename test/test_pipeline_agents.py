"""Unit tests for the four A2A pipeline agents.

Covers: FactCheckerGeminiAgent, AnalystClaudeAgent,
        ReviewerClaudeAgent, CoderOpenAIPipelineAgent

All external SDK calls are mocked. Tests verify:
- Correct defaults (name, instructions, description, model)
- Correct inheritance from provider base
- peers field wired as expected when declared
- run() reaches the provider SDK with the right arguments
- delegate() routes to the correct peer
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.ai.a2a.protocol import A2APeer


# ---------------------------------------------------------------------------
# Shared mock factories (mirroring test_provider_bases.py patterns)
# ---------------------------------------------------------------------------

def _make_peer(name: str, output: str = "peer output") -> A2APeer:
    """Build a mocked A2APeer for wiring peer-delegation tests.

    Args:
        name: Peer name, also used to derive the mocked agent's `agent_id`.
        output: Value returned by the mocked peer agent's `run()` call.

    Returns:
        An `A2APeer` wrapping a `MagicMock` agent configured with the given
        `agent_id` and `run()` return value.
    """
    agent = MagicMock()
    agent.agent_id = f"{name}-id"
    agent.run.return_value = output
    return A2APeer(name=name, description=f"{name} peer", agent=agent)


def _plain_claude_response(text: str) -> MagicMock:
    """Build a mocked Anthropic Messages API response with a single text block.

    Args:
        text: Text content to place in the mocked response's single content block.

    Returns:
        A `MagicMock` shaped like an Anthropic response with `stop_reason`
        set to "end_turn" and `content` containing one text block.
    """
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


def _plain_gemini_response(text: str) -> MagicMock:
    """Build a mocked Gemini chat response with no function-call parts.

    Args:
        text: Text content to place on the mocked response's `text` attribute.

    Returns:
        A `MagicMock` shaped like a Gemini response with `text` set and an
        empty `candidates` list.
    """
    resp = MagicMock()
    resp.text = text
    resp.candidates = []  # no function-call parts
    return resp


# ---------------------------------------------------------------------------
# FactCheckerGeminiAgent
# ---------------------------------------------------------------------------

class TestFactCheckerGeminiAgent(unittest.TestCase):
    """Tests for FactCheckerGeminiAgent defaults, inheritance, and run() behavior."""

    def _make(self, **kwargs):
        """Construct the FactCheckerGeminiAgent under test.

        Args:
            **kwargs: Keyword arguments forwarded to the `FactCheckerGeminiAgent`
                constructor.

        Returns:
            A new `FactCheckerGeminiAgent` instance.
        """
        from src.app.agents.fact_checker_gemini_agent import FactCheckerGeminiAgent
        return FactCheckerGeminiAgent(**kwargs)

    def test_default_name(self):
        """Verify the agent's default name is "Fact Checker"."""
        agent = self._make()
        self.assertEqual(agent.name, "Fact Checker")

    def test_default_model(self):
        """Verify the agent's default model is "gemini-2.0-flash"."""
        agent = self._make()
        self.assertEqual(agent.model, "gemini-2.0-flash")

    def test_description_mentions_fact(self):
        """Verify the agent's description references "fact"."""
        agent = self._make()
        self.assertIn("fact", agent.description.lower())

    def test_instructions_mention_verdict(self):
        """Verify the agent's instructions include the "VERDICT" keyword."""
        agent = self._make()
        self.assertIn("VERDICT", agent.instructions)

    def test_inherits_gemini_base(self):
        """Verify the agent subclasses GeminiBaseAgent."""
        from src.ai.base_gemini import GeminiBaseAgent
        from src.app.agents.fact_checker_gemini_agent import FactCheckerGeminiAgent
        self.assertTrue(issubclass(FactCheckerGeminiAgent, GeminiBaseAgent))

    def test_inherits_abstract_base(self):
        """Verify the agent subclasses AbstractBaseAgent."""
        from src.ai.base_agent import AbstractBaseAgent
        from src.app.agents.fact_checker_gemini_agent import FactCheckerGeminiAgent
        self.assertTrue(issubclass(FactCheckerGeminiAgent, AbstractBaseAgent))

    def test_no_peers_by_default(self):
        """Verify the agent has no peers when constructed without any."""
        agent = self._make()
        self.assertFalse(agent.has_peers())

    def test_agent_id_assigned(self):
        """Verify the agent is assigned a non-empty agent_id."""
        agent = self._make()
        self.assertTrue(agent.agent_id)

    def test_name_can_be_overridden(self):
        """Verify a custom name passed to the constructor is honored."""
        agent = self._make(name="Custom Checker")
        self.assertEqual(agent.name, "Custom Checker")

    def test_model_can_be_overridden(self):
        """Verify a custom model passed to the constructor is honored."""
        agent = self._make(model="gemini-1.5-pro")
        self.assertEqual(agent.model, "gemini-1.5-pro")

    @patch("src.ai.base_gemini.genai")
    def test_run_calls_send_message(self, mock_genai):
        """Verify run() forwards the input text to the Gemini chat's send_message and returns its text."""
        mock_chat = MagicMock()
        mock_chat.send_message.return_value = _plain_gemini_response("VERDICT: True")
        mock_genai.GenerativeModel.return_value.start_chat.return_value = mock_chat

        agent = self._make()
        result = agent.run("Python is widely used.")

        mock_chat.send_message.assert_called_once_with("Python is widely used.")
        self.assertEqual(result, "VERDICT: True")

    @patch("src.ai.base_gemini.genai")
    def test_run_builds_model_with_correct_params(self, mock_genai):
        """Verify run() builds the GenerativeModel with the agent's model name and instructions."""
        mock_chat = MagicMock()
        mock_chat.send_message.return_value = _plain_gemini_response("ok")
        mock_genai.GenerativeModel.return_value.start_chat.return_value = mock_chat

        agent = self._make()
        agent.run("claim")

        mock_genai.GenerativeModel.assert_called_once_with(
            model_name="gemini-2.0-flash",
            system_instruction=agent.instructions,
        )


# ---------------------------------------------------------------------------
# AnalystClaudeAgent
# ---------------------------------------------------------------------------

class TestAnalystClaudeAgent(unittest.TestCase):
    """Tests for AnalystClaudeAgent defaults, inheritance, run(), and delegate() behavior."""

    def _make(self, **kwargs):
        """Construct the AnalystClaudeAgent under test.

        Args:
            **kwargs: Keyword arguments forwarded to the `AnalystClaudeAgent`
                constructor.

        Returns:
            A new `AnalystClaudeAgent` instance.
        """
        from src.app.agents.analyst_claude_agent import AnalystClaudeAgent
        return AnalystClaudeAgent(**kwargs)

    def test_default_name(self):
        """Verify the agent's default name is "Analyst"."""
        self.assertEqual(self._make().name, "Analyst")

    def test_default_model(self):
        """Verify the agent's default model is "claude-sonnet-4-6"."""
        self.assertEqual(self._make().model, "claude-sonnet-4-6")

    def test_description_mentions_analysis(self):
        """Verify the agent's description references "analys"."""
        agent = self._make()
        self.assertIn("analys", agent.description.lower())

    def test_instructions_mention_analysis(self):
        """Verify the agent's instructions reference "analyst"."""
        agent = self._make()
        self.assertIn("analyst", agent.instructions.lower())

    def test_inherits_claude_base(self):
        """Verify the agent subclasses ClaudeBaseAgent."""
        from src.ai.base_claude import ClaudeBaseAgent
        from src.app.agents.analyst_claude_agent import AnalystClaudeAgent
        self.assertTrue(issubclass(AnalystClaudeAgent, ClaudeBaseAgent))

    def test_inherits_abstract_base(self):
        """Verify the agent subclasses AbstractBaseAgent."""
        from src.ai.base_agent import AbstractBaseAgent
        from src.app.agents.analyst_claude_agent import AnalystClaudeAgent
        self.assertTrue(issubclass(AnalystClaudeAgent, AbstractBaseAgent))

    def test_no_peers_by_default(self):
        """Verify the agent has no peers when constructed without any."""
        self.assertFalse(self._make().has_peers())

    def test_accepts_fact_checker_peer(self):
        """Verify a fact_checker peer passed to the constructor is wired in."""
        peer = _make_peer("fact_checker")
        agent = self._make(peers=[peer])
        self.assertTrue(agent.has_peers())
        self.assertIn("fact_checker", agent.peer_names)

    def test_name_can_be_overridden(self):
        """Verify a custom name passed to the constructor is honored."""
        self.assertEqual(self._make(name="Research Analyst").name, "Research Analyst")

    def test_model_can_be_overridden(self):
        """Verify a custom model passed to the constructor is honored."""
        self.assertEqual(self._make(model="claude-opus-4-8").model, "claude-opus-4-8")

    @patch("src.ai.base_claude.Anthropic")
    def test_run_no_peers_returns_text(self, mock_anthropic):
        """Verify run() returns the text content from the Anthropic response when there are no peers."""
        mock_anthropic.return_value.messages.create.return_value = (
            _plain_claude_response("Analysis complete.")
        )
        result = self._make().run("Analyze the market.")
        self.assertEqual(result, "Analysis complete.")

    @patch("src.ai.base_claude.Anthropic")
    def test_run_passes_instructions_as_system(self, mock_anthropic):
        """Verify run() passes the agent's instructions as the system prompt."""
        mock_anthropic.return_value.messages.create.return_value = (
            _plain_claude_response("ok")
        )
        agent = self._make()
        agent.run("task")
        _, kwargs = mock_anthropic.return_value.messages.create.call_args
        self.assertEqual(kwargs["system"], agent.instructions)

    def test_delegate_routes_to_fact_checker_peer(self):
        """Verify delegate() routes to the fact_checker peer and returns its output and sender id."""
        peer = _make_peer("fact_checker", output="VERDICT: True")
        agent = self._make(peers=[peer])
        resp = agent.delegate("fact_checker", "LLMs are powerful.")
        self.assertEqual(resp.output, "VERDICT: True")
        self.assertEqual(resp.sender, "fact_checker-id")

    def test_delegate_threads_trace_id(self):
        """Verify delegate() threads the given trace_id through to the response."""
        peer = _make_peer("fact_checker")
        agent = self._make(peers=[peer])
        resp = agent.delegate("fact_checker", "claim", trace_id="analyst-trace-1")
        self.assertEqual(resp.trace_id, "analyst-trace-1")

    def test_delegate_unknown_peer_raises(self):
        """Verify delegate() raises KeyError when the named peer is not registered."""
        agent = self._make()
        with self.assertRaises(KeyError):
            agent.delegate("nobody", "task")


# ---------------------------------------------------------------------------
# ReviewerClaudeAgent
# ---------------------------------------------------------------------------

class TestReviewerClaudeAgent(unittest.TestCase):
    """Tests for ReviewerClaudeAgent defaults, inheritance, run(), and peer usability."""

    def _make(self, **kwargs):
        """Construct the ReviewerClaudeAgent under test.

        Args:
            **kwargs: Keyword arguments forwarded to the `ReviewerClaudeAgent`
                constructor.

        Returns:
            A new `ReviewerClaudeAgent` instance.
        """
        from src.app.agents.reviewer_claude_agent import ReviewerClaudeAgent
        return ReviewerClaudeAgent(**kwargs)

    def test_default_name(self):
        """Verify the agent's default name is "Code Reviewer"."""
        self.assertEqual(self._make().name, "Code Reviewer")

    def test_default_model(self):
        """Verify the agent's default model is "claude-sonnet-4-6"."""
        self.assertEqual(self._make().model, "claude-sonnet-4-6")

    def test_description_mentions_review(self):
        """Verify the agent's description references "review"."""
        self.assertIn("review", self._make().description.lower())

    def test_instructions_contain_verdict_keywords(self):
        """Verify the agent's instructions include both APPROVE and REQUEST_CHANGES keywords."""
        instructions = self._make().instructions
        self.assertIn("APPROVE", instructions)
        self.assertIn("REQUEST_CHANGES", instructions)

    def test_inherits_claude_base(self):
        """Verify the agent subclasses ClaudeBaseAgent."""
        from src.ai.base_claude import ClaudeBaseAgent
        from src.app.agents.reviewer_claude_agent import ReviewerClaudeAgent
        self.assertTrue(issubclass(ReviewerClaudeAgent, ClaudeBaseAgent))

    def test_inherits_abstract_base(self):
        """Verify the agent subclasses AbstractBaseAgent."""
        from src.ai.base_agent import AbstractBaseAgent
        from src.app.agents.reviewer_claude_agent import ReviewerClaudeAgent
        self.assertTrue(issubclass(ReviewerClaudeAgent, AbstractBaseAgent))

    def test_no_peers_by_default(self):
        """Verify the agent has no peers when constructed without any."""
        self.assertFalse(self._make().has_peers())

    def test_agent_id_assigned(self):
        """Verify the agent is assigned a non-empty agent_id."""
        self.assertTrue(self._make().agent_id)

    def test_name_can_be_overridden(self):
        """Verify a custom name passed to the constructor is honored."""
        self.assertEqual(self._make(name="Senior Reviewer").name, "Senior Reviewer")

    @patch("src.ai.base_claude.Anthropic")
    def test_run_returns_review_text(self, mock_anthropic):
        """Verify run() returns the review text content from the Anthropic response."""
        mock_anthropic.return_value.messages.create.return_value = (
            _plain_claude_response("APPROVE — clean code.")
        )
        result = self._make().run("def foo(): pass")
        self.assertEqual(result, "APPROVE — clean code.")

    @patch("src.ai.base_claude.Anthropic")
    def test_run_forwards_code_as_user_content(self, mock_anthropic):
        """Verify run() forwards the input code as the user message content."""
        mock_anthropic.return_value.messages.create.return_value = (
            _plain_claude_response("ok")
        )
        self._make().run("def bar(): return 1")
        _, kwargs = mock_anthropic.return_value.messages.create.call_args
        self.assertEqual(kwargs["messages"][0]["content"], "def bar(): return 1")

    def test_usable_as_peer_for_coder(self):
        """Verify a ReviewerClaudeAgent instance can be wrapped as an A2APeer."""
        from src.app.agents.reviewer_claude_agent import ReviewerClaudeAgent
        reviewer = ReviewerClaudeAgent()
        peer = A2APeer(name="reviewer", description=reviewer.description, agent=reviewer)
        self.assertEqual(peer.name, "reviewer")
        self.assertIs(peer.agent, reviewer)


# ---------------------------------------------------------------------------
# CoderOpenAIPipelineAgent
# ---------------------------------------------------------------------------

class TestCoderOpenAIPipelineAgent(unittest.TestCase):
    """Tests for CoderOpenAIPipelineAgent defaults, inheritance, run(), and delegate() behavior."""

    def _make(self, **kwargs):
        """Construct the CoderOpenAIPipelineAgent under test.

        Args:
            **kwargs: Keyword arguments forwarded to the `CoderOpenAIPipelineAgent`
                constructor.

        Returns:
            A new `CoderOpenAIPipelineAgent` instance.
        """
        from src.app.agents.coder_openai_pipeline_agent import CoderOpenAIPipelineAgent
        return CoderOpenAIPipelineAgent(**kwargs)

    def test_default_name(self):
        """Verify the agent's default name is "Python Coder"."""
        self.assertEqual(self._make().name, "Python Coder")

    def test_default_model(self):
        """Verify the agent's default model is "gpt-4o"."""
        self.assertEqual(self._make().model, "gpt-4o")

    def test_description_mentions_code(self):
        """Verify the agent's description references "code"."""
        self.assertIn("code", self._make().description.lower())

    def test_instructions_mention_python(self):
        """Verify the agent's instructions reference "Python"."""
        self.assertIn("Python", self._make().instructions)

    def test_instructions_mention_reviewer(self):
        """Verify the agent's instructions reference "reviewer"."""
        self.assertIn("reviewer", self._make().instructions.lower())

    def test_inherits_openai_base(self):
        """Verify the agent subclasses OpenAIBaseAgent."""
        from src.ai.base_openai import OpenAIBaseAgent
        from src.app.agents.coder_openai_pipeline_agent import CoderOpenAIPipelineAgent
        self.assertTrue(issubclass(CoderOpenAIPipelineAgent, OpenAIBaseAgent))

    def test_inherits_abstract_base(self):
        """Verify the agent subclasses AbstractBaseAgent."""
        from src.ai.base_agent import AbstractBaseAgent
        from src.app.agents.coder_openai_pipeline_agent import CoderOpenAIPipelineAgent
        self.assertTrue(issubclass(CoderOpenAIPipelineAgent, AbstractBaseAgent))

    def test_no_peers_by_default(self):
        """Verify the agent has no peers when constructed without any."""
        self.assertFalse(self._make().has_peers())

    def test_accepts_reviewer_peer(self):
        """Verify a reviewer peer passed to the constructor is wired in."""
        peer = _make_peer("reviewer")
        agent = self._make(peers=[peer])
        self.assertTrue(agent.has_peers())
        self.assertIn("reviewer", agent.peer_names)

    def test_name_can_be_overridden(self):
        """Verify a custom name passed to the constructor is honored."""
        self.assertEqual(self._make(name="Go Coder").name, "Go Coder")

    def test_model_can_be_overridden(self):
        """Verify a custom model passed to the constructor is honored."""
        self.assertEqual(self._make(model="gpt-4o-mini").model, "gpt-4o-mini")

    @patch("src.ai.base_openai.Runner")
    @patch("src.ai.base_openai.Agent")
    def test_run_returns_final_output(self, mock_agent_cls, mock_runner):
        """Verify run() returns the Runner's final_output value."""
        mock_runner.run_sync.return_value = MagicMock(final_output="def fib(n): ...")
        result = self._make().run("Write fibonacci")
        self.assertEqual(result, "def fib(n): ...")

    @patch("src.ai.base_openai.Runner")
    @patch("src.ai.base_openai.Agent")
    def test_run_creates_agent_with_model(self, mock_agent_cls, mock_runner):
        """Verify run() constructs the underlying Agent with the expected name, instructions, and model."""
        mock_runner.run_sync.return_value = MagicMock(final_output="ok")
        agent = self._make()
        agent.run("task")
        mock_agent_cls.assert_called_once_with(
            name="Python Coder",
            instructions=agent.instructions,
            model="gpt-4o",
        )

    @patch("src.ai.base_openai.Runner")
    @patch("src.ai.base_openai.Agent")
    def test_run_passes_message_to_runner(self, mock_agent_cls, mock_runner):
        """Verify run() passes the constructed agent and input message to Runner.run_sync."""
        mock_instance = MagicMock()
        mock_agent_cls.return_value = mock_instance
        mock_runner.run_sync.return_value = MagicMock(final_output="ok")
        self._make().run("write binary search")
        mock_runner.run_sync.assert_called_once_with(mock_instance, "write binary search")

    def test_delegate_to_reviewer_peer(self):
        """Verify delegate() routes to the reviewer peer and returns its output and sender id."""
        reviewer_peer = _make_peer("reviewer", output="APPROVE — good code.")
        coder = self._make(peers=[reviewer_peer])
        resp = coder.delegate("reviewer", "def sort(arr): arr.sort()")
        self.assertEqual(resp.output, "APPROVE — good code.")
        self.assertEqual(resp.sender, "reviewer-id")

    def test_delegate_threads_trace_id(self):
        """Verify delegate() threads the given trace_id through to the response."""
        peer = _make_peer("reviewer")
        coder = self._make(peers=[peer])
        resp = coder.delegate("reviewer", "code", trace_id="pipeline-trace-99")
        self.assertEqual(resp.trace_id, "pipeline-trace-99")

    def test_two_agents_have_distinct_ids(self):
        """Verify two separately constructed agents receive distinct agent_ids."""
        a = self._make()
        b = self._make()
        self.assertNotEqual(a.agent_id, b.agent_id)


# ---------------------------------------------------------------------------
# Cross-agent identity and peer wiring sanity checks
# ---------------------------------------------------------------------------

class TestCrossAgentWiring(unittest.TestCase):
    """Tests for identity uniqueness and peer wiring across the four pipeline agents."""

    def test_all_four_agents_have_unique_ids(self):
        """Verify all four pipeline agents receive distinct agent_ids."""
        from src.app.agents.analyst_claude_agent import AnalystClaudeAgent
        from src.app.agents.coder_openai_pipeline_agent import CoderOpenAIPipelineAgent
        from src.app.agents.fact_checker_gemini_agent import FactCheckerGeminiAgent
        from src.app.agents.reviewer_claude_agent import ReviewerClaudeAgent

        ids = [
            FactCheckerGeminiAgent().agent_id,
            AnalystClaudeAgent().agent_id,
            ReviewerClaudeAgent().agent_id,
            CoderOpenAIPipelineAgent().agent_id,
        ]
        self.assertEqual(len(ids), len(set(ids)))

    def test_analyst_fact_checker_pipeline_wiring(self):
        """Verify an AnalystClaudeAgent wired with a FactCheckerGeminiAgent peer references it correctly."""
        from src.app.agents.analyst_claude_agent import AnalystClaudeAgent
        from src.app.agents.fact_checker_gemini_agent import FactCheckerGeminiAgent

        fc = FactCheckerGeminiAgent()
        analyst = AnalystClaudeAgent(
            peers=[A2APeer(name="fact_checker", description=fc.description, agent=fc)]
        )
        self.assertEqual(analyst.peers[0].agent.agent_id, fc.agent_id)
        self.assertEqual(analyst.peers[0].description, fc.description)

    def test_coder_reviewer_pipeline_wiring(self):
        """Verify a CoderOpenAIPipelineAgent wired with a ReviewerClaudeAgent peer references it correctly."""
        from src.app.agents.coder_openai_pipeline_agent import CoderOpenAIPipelineAgent
        from src.app.agents.reviewer_claude_agent import ReviewerClaudeAgent

        rv = ReviewerClaudeAgent()
        coder = CoderOpenAIPipelineAgent(
            peers=[A2APeer(name="reviewer", description=rv.description, agent=rv)]
        )
        self.assertEqual(coder.peers[0].agent.agent_id, rv.agent_id)

    def test_model_copy_preserves_peers(self):
        """model_copy (used by orchestrator) must carry peers through."""
        from src.app.agents.analyst_claude_agent import AnalystClaudeAgent

        peer = _make_peer("fact_checker")
        original = AnalystClaudeAgent(peers=[peer])
        copied = original.model_copy(update={"name": "Analyst v2"})
        self.assertTrue(copied.has_peers())
        self.assertIn("fact_checker", copied.peer_names)
        self.assertEqual(copied.name, "Analyst v2")


if __name__ == "__main__":
    unittest.main()
