"""Unit tests for src/resource/base_gemini.py."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from src.resource.base_gemini import BaseAgent


# ---------------------------------------------------------------------------
# Concrete subclass — BaseAgent is abstract (ABC), so we need a concrete
# implementation to instantiate it in tests.
# ---------------------------------------------------------------------------

class ConcreteAgent(BaseAgent):
    """Minimal concrete subclass used only in tests."""


# ---------------------------------------------------------------------------
# Instantiation tests
# ---------------------------------------------------------------------------

class TestBaseAgentInstantiation(unittest.TestCase):
    """Tests for BaseAgent field validation and default values."""

    def test_creates_with_name_and_instructions(self) -> None:
        """Valid name and instructions produce a correctly populated instance."""
        agent = ConcreteAgent(name="Test Agent", instructions="Do something useful")
        self.assertEqual(agent.name, "Test Agent")
        self.assertEqual(agent.instructions, "Do something useful")

    def test_default_model_is_gemini_flash(self) -> None:
        """Default model is gemini-2.0-flash when no model is supplied."""
        agent = ConcreteAgent(name="Test", instructions="Test")
        self.assertEqual(agent.model, "gemini-2.0-flash")

    def test_model_can_be_overridden(self) -> None:
        """A custom model string is stored unchanged on the instance."""
        agent = ConcreteAgent(
            name="Test", instructions="Test", model="gemini-1.5-pro"
        )
        self.assertEqual(agent.model, "gemini-1.5-pro")

    def test_missing_name_raises_validation_error(self) -> None:
        """Omitting `name` must raise a pydantic ValidationError."""
        with self.assertRaises(ValidationError):
            ConcreteAgent(instructions="Some instructions")  # type: ignore[call-arg]

    def test_missing_instructions_raises_validation_error(self) -> None:
        """Omitting `instructions` must raise a pydantic ValidationError."""
        with self.assertRaises(ValidationError):
            ConcreteAgent(name="Some name")  # type: ignore[call-arg]

    def test_missing_both_fields_raises_validation_error(self) -> None:
        """Omitting both required fields must raise a pydantic ValidationError."""
        with self.assertRaises(ValidationError):
            ConcreteAgent()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# run() behaviour tests
# ---------------------------------------------------------------------------

class TestBaseAgentRun(unittest.TestCase):
    """Tests for BaseAgent.run() — all external genai calls are mocked."""

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _make_agent(self, **overrides: str) -> ConcreteAgent:
        """Build a ConcreteAgent with default name/instructions, overridable by kwargs.

        Args:
            **overrides: Field values overriding the defaults (name, instructions, model).

        Returns:
            ConcreteAgent: The constructed test agent instance.
        """
        defaults = {"name": "Test", "instructions": "System instructions"}
        return ConcreteAgent(**{**defaults, **overrides})

    def _make_mock_genai(self, response_text: str = "Gemini response") -> MagicMock:
        """Return a mock genai module wired up like the real one.

        Structure (updated for start_chat / send_message API):
            genai.configure(...)
            genai.GenerativeModel(...) -> mock_model
            mock_model.start_chat() -> mock_chat
            mock_chat.send_message(...) -> mock_response
            mock_response.candidates -> [] (no function calls)
            mock_response.text -> response_text
        """
        mock_genai = MagicMock()
        mock_model = MagicMock()
        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.text = response_text
        mock_response.candidates = []          # no function-call parts → loop exits immediately
        mock_chat.send_message.return_value = mock_response
        mock_model.start_chat.return_value = mock_chat
        mock_genai.GenerativeModel.return_value = mock_model
        return mock_genai

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    @patch("src.resource.base_gemini.genai")
    def test_instantiation_calls_genai_configure_with_api_key(
        self, mock_genai: MagicMock
    ) -> None:
        """genai.configure must be called exactly once (at instantiation) with an api_key kwarg."""
        mock_genai_wired = self._make_mock_genai()
        mock_genai.configure = mock_genai_wired.configure
        mock_genai.GenerativeModel = mock_genai_wired.GenerativeModel

        self._make_agent()

        mock_genai.configure.assert_called_once()
        _, kwargs = mock_genai.configure.call_args
        self.assertIn("api_key", kwargs)

    @patch("src.resource.base_gemini.genai")
    def test_run_constructs_generative_model_with_correct_params(
        self, mock_genai: MagicMock
    ) -> None:
        """GenerativeModel must be built with model_name and system_instruction."""
        mock_genai_wired = self._make_mock_genai()
        mock_genai.configure = mock_genai_wired.configure
        mock_genai.GenerativeModel = mock_genai_wired.GenerativeModel

        agent = self._make_agent(
            name="Test", instructions="System instructions", model="gemini-2.0-flash"
        )
        agent.run("User message")

        mock_genai.GenerativeModel.assert_called_once_with(
            model_name="gemini-2.0-flash",
            system_instruction="System instructions",
        )

    @patch("src.resource.base_gemini.genai")
    def test_run_uses_overridden_model(self, mock_genai: MagicMock) -> None:
        """When a custom model is set, GenerativeModel must receive that model_name."""
        mock_genai_wired = self._make_mock_genai()
        mock_genai.configure = mock_genai_wired.configure
        mock_genai.GenerativeModel = mock_genai_wired.GenerativeModel

        agent = self._make_agent(model="gemini-1.5-pro")
        agent.run("question")

        _, kwargs = mock_genai.GenerativeModel.call_args
        self.assertEqual(kwargs["model_name"], "gemini-1.5-pro")

    @patch("src.resource.base_gemini.genai")
    def test_run_calls_send_message_with_message(
        self, mock_genai: MagicMock
    ) -> None:
        """send_message must be called with the exact message string passed to run()."""
        mock_genai_wired = self._make_mock_genai()
        mock_genai.configure = mock_genai_wired.configure
        mock_genai.GenerativeModel = mock_genai_wired.GenerativeModel

        agent = self._make_agent()
        agent.run("What is 2 + 2?")

        mock_chat = mock_genai.GenerativeModel.return_value.start_chat.return_value
        mock_chat.send_message.assert_called_once_with("What is 2 + 2?")

    @patch("src.resource.base_gemini.genai")
    def test_run_returns_response_text(self, mock_genai: MagicMock) -> None:
        """run() must return the .text attribute of the send_message response."""
        mock_genai_wired = self._make_mock_genai(response_text="Gemini's answer")
        mock_genai.configure = mock_genai_wired.configure
        mock_genai.GenerativeModel = mock_genai_wired.GenerativeModel

        agent = self._make_agent()
        result = agent.run("any message")

        self.assertEqual(result, "Gemini's answer")


if __name__ == "__main__":
    unittest.main()
