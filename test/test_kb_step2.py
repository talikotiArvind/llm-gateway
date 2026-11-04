"""Unit tests for Step 2: kb_summariser (Claude API calls mocked)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pipeline.second_brain.kb_models import (
    ChangeRecord,
    ChangeType,
    ClassInfo,
    ModuleSnapshot,
    LayerType,
)
from pipeline.second_brain.kb_summariser import KBSummariser, _pick_model, _HAIKU, _SONNET


def _make_record(diff_lines: int = 10, file_path: str = "src/ai/base_claude.py") -> ChangeRecord:
    """Build a sample ChangeRecord with a synthetic diff of the given size.

    Args:
        diff_lines: Number of added lines to synthesize in the diff snippet.
        file_path: File path to attribute the change to.

    Returns:
        ChangeRecord: A change record wrapping a single-class module snapshot.
    """
    snap = ModuleSnapshot(
        file_path=file_path,
        module_slug="src--ai--base_claude",
        layer=LayerType.data_access,
        classes=[ClassInfo(name="ClaudeBaseAgent", docstring="Wraps Anthropic.", methods=["run(task)"])],
        module_docstring="Claude base agent.",
        top_level_functions=[],
        line_count=120,
    )
    diff = "\n".join(f"+line {i}" for i in range(diff_lines))
    return ChangeRecord(
        file_path=file_path,
        change_type=ChangeType.modified,
        pr_number=7,
        pr_title="feat: add vault write-back",
        pr_body="Adds write-back to vault after run().",
        diff_stat=f"+{diff_lines} -0 lines",
        diff_snippet=diff,
        snapshot=snap,
        recorded_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
    )


def _mock_anthropic(prose: str = "This module wraps the Anthropic SDK.") -> MagicMock:
    """Build a mock Anthropic client whose messages.create() returns given prose.

    Args:
        prose: Text to embed in the mocked response content block.

    Returns:
        MagicMock: A mock Anthropic client wired to return a response.
    """
    block = MagicMock()
    block.text = prose
    response = MagicMock()
    response.content = [block]
    client = MagicMock()
    client.messages.create.return_value = response
    return client


class TestPickModel(unittest.TestCase):
    """Tests for the _pick_model diff-size-based model selection helper."""

    def test_small_diff_uses_haiku(self):
        """A diff well under the threshold selects the Haiku model."""
        diff = "\n".join(f"+line {i}" for i in range(50))
        self.assertEqual(_pick_model(diff), _HAIKU)

    def test_large_diff_uses_sonnet(self):
        """A diff well over the threshold selects the Sonnet model."""
        diff = "\n".join(f"+line {i}" for i in range(250))
        self.assertEqual(_pick_model(diff), _SONNET)

    def test_boundary_200_uses_haiku(self):
        """A diff of exactly 200 lines still selects Haiku."""
        diff = "\n".join(f"+line {i}" for i in range(200))
        self.assertEqual(_pick_model(diff), _HAIKU)

    def test_boundary_201_uses_sonnet(self):
        """A diff of 201 lines crosses the threshold and selects Sonnet."""
        diff = "\n".join(f"+line {i}" for i in range(201))
        self.assertEqual(_pick_model(diff), _SONNET)


class TestKBSummariser(unittest.TestCase):
    """Tests for KBSummariser with the Anthropic client mocked."""

    def _summariser(self, prose: str = "Test prose.") -> tuple[KBSummariser, MagicMock]:
        """Build a KBSummariser wired to a mocked Anthropic client.

        Args:
            prose: Text the mocked client should return as the summary.

        Returns:
            tuple[KBSummariser, MagicMock]: The summariser instance and its mock client.
        """
        mock_client = _mock_anthropic(prose)
        s = KBSummariser.__new__(KBSummariser)
        s._client = mock_client
        return s, mock_client

    def test_summarise_fills_prose(self):
        """summarise() copies the mocked API response text into prose_summary."""
        s, _ = self._summariser("ClaudeBaseAgent wraps the SDK.")
        result = s.summarise(_make_record())
        self.assertEqual(result.prose_summary, "ClaudeBaseAgent wraps the SDK.")

    def test_summarise_fills_model_used(self):
        """summarise() records the Haiku model for a small diff."""
        s, _ = self._summariser()
        result = s.summarise(_make_record(diff_lines=10))
        self.assertEqual(result.model_used, _HAIKU)

    def test_summarise_large_diff_uses_sonnet(self):
        """summarise() calls the Anthropic API with the Sonnet model for a large diff."""
        s, mock_client = self._summariser()
        s.summarise(_make_record(diff_lines=250))
        call_kwargs = mock_client.messages.create.call_args
        self.assertEqual(call_kwargs.kwargs["model"], _SONNET)

    def test_summarise_small_diff_uses_haiku(self):
        """summarise() calls the Anthropic API with the Haiku model for a small diff."""
        s, mock_client = self._summariser()
        s.summarise(_make_record(diff_lines=10))
        call_kwargs = mock_client.messages.create.call_args
        self.assertEqual(call_kwargs.kwargs["model"], _HAIKU)

    def test_summarise_api_failure_returns_error_note(self):
        """summarise() falls back to an error placeholder when the API call raises."""
        s = KBSummariser.__new__(KBSummariser)
        s._client = MagicMock()
        s._client.messages.create.side_effect = Exception("timeout")
        result = s.summarise(_make_record())
        self.assertIn("summary unavailable", result.prose_summary)
        self.assertEqual(result.model_used, "error")

    def test_summarise_many_returns_all(self):
        """summarise_many() returns one populated result per input record."""
        s, _ = self._summariser("prose")
        records = [_make_record(), _make_record(file_path="src/ai/base_openai.py")]
        results = s.summarise_many(records)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.prose_summary for r in results))

    def test_summarise_to_note_returns_kbnote(self):
        """summarise_to_note() maps record and snapshot fields onto a KBNote."""
        s, _ = self._summariser("ClaudeBaseAgent is the data-access wrapper.")
        note = s.summarise_to_note(_make_record())
        self.assertEqual(note.module, "src/ai/base_claude.py")
        self.assertEqual(note.last_pr, 7)
        self.assertEqual(note.classes, ["ClaudeBaseAgent"])
        self.assertIn("run(task)", note.key_methods)
        self.assertEqual(note.layer, "data-access")

    def test_summarise_to_note_without_snapshot(self):
        """summarise_to_note() defaults classes to empty and layer to unknown without a snapshot."""
        s, _ = self._summariser("No AST available.")
        record = _make_record()
        record = record.model_copy(update={"snapshot": None})
        note = s.summarise_to_note(record)
        self.assertEqual(note.classes, [])
        self.assertEqual(note.layer, "unknown")

    def test_api_prompt_contains_file_path(self):
        """The prompt sent to the API must include the changed file's path."""
        s, mock_client = self._summariser()
        s.summarise(_make_record())
        prompt_text = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("src/ai/base_claude.py", prompt_text)

    def test_api_prompt_contains_pr_number(self):
        """The prompt sent to the API must include the PR number."""
        s, mock_client = self._summariser()
        s.summarise(_make_record())
        prompt_text = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("PR #7", prompt_text)


if __name__ == "__main__":
    unittest.main()
