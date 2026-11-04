"""Unit tests for Step 3: change_detector, kb_initialiser, kb_runner."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from pipeline.second_brain.change_detector import ChangeDetector, _is_tracked, _parse_status
from pipeline.second_brain.kb_models import ChangeType
from pipeline.second_brain.kb_initialiser import _collect_py_files


# ---------------------------------------------------------------------------
# _is_tracked
# ---------------------------------------------------------------------------

class TestIsTracked(unittest.TestCase):
    """Tests for the _is_tracked file-path classification helper."""

    def test_src_py_tracked(self):
        """A .py file under src/ is tracked."""
        self.assertTrue(_is_tracked("src/resource/base_claude.py"))

    def test_pipeline_py_tracked(self):
        """A .py file under pipeline/ is tracked."""
        self.assertTrue(_is_tracked("pipeline/second_brain/vault_retriever.py"))

    def test_rag_pipeline_py_tracked(self):
        """A .py file under rag_pipeline/ is tracked."""
        self.assertTrue(_is_tracked("rag_pipeline/api/main.py"))

    def test_orchestrator_tracked(self):
        """The top-level orchestrator.py file is tracked."""
        self.assertTrue(_is_tracked("orchestrator.py"))

    def test_test_file_not_tracked(self):
        """A file under test/ is not tracked."""
        self.assertFalse(_is_tracked("test/test_base_claude.py"))

    def test_non_py_not_tracked(self):
        """A non-.py file is not tracked."""
        self.assertFalse(_is_tracked("src/resource/config.yaml"))

    def test_docs_not_tracked(self):
        """A file under docs/ is not tracked."""
        self.assertFalse(_is_tracked("docs/index.md"))


# ---------------------------------------------------------------------------
# _parse_status
# ---------------------------------------------------------------------------

class TestParseStatus(unittest.TestCase):
    """Tests for the _parse_status git status-code translation helper."""

    def test_added(self):
        """Status code 'A' maps to ChangeType.added."""
        self.assertEqual(_parse_status("A"), ChangeType.added)

    def test_modified(self):
        """Status code 'M' maps to ChangeType.modified."""
        self.assertEqual(_parse_status("M"), ChangeType.modified)

    def test_deleted(self):
        """Status code 'D' maps to ChangeType.deleted."""
        self.assertEqual(_parse_status("D"), ChangeType.deleted)

    def test_renamed_treated_as_modified(self):
        """A rename status code (e.g. 'R100') maps to ChangeType.modified."""
        self.assertEqual(_parse_status("R100"), ChangeType.modified)


# ---------------------------------------------------------------------------
# ChangeDetector
# ---------------------------------------------------------------------------

class TestChangeDetector(unittest.TestCase):
    """Tests for ChangeDetector.detect() with the underlying git calls mocked."""

    def _make_detector(self, git_output: str) -> ChangeDetector:
        """Build a ChangeDetector whose internal git runner returns fixed output.

        Args:
            git_output: The text to return from the mocked git call.

        Returns:
            ChangeDetector: A detector wired to the given mocked git output.
        """
        detector = ChangeDetector(repo_root=".")
        detector._run_git = MagicMock(return_value=git_output)
        return detector

    @patch("pipeline.second_brain.change_detector._run")
    def test_detect_modified_file(self, mock_run):
        """detect() returns a record with the modified file's path, type, and PR number."""
        mock_run.side_effect = [
            "M\tsrc/resource/base_claude.py",   # name-status
            "@@ -1,3 +1,5 @@\n+new line\n+another",  # diff
        ]
        detector = ChangeDetector(repo_root=".")
        records = detector.detect(pr_number=5, pr_title="feat: test")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].file_path, "src/resource/base_claude.py")
        self.assertEqual(records[0].change_type, ChangeType.modified)
        self.assertEqual(records[0].pr_number, 5)

    @patch("pipeline.second_brain.change_detector._run")
    def test_detect_skips_test_files(self, mock_run):
        """detect() excludes test files from the returned change records."""
        mock_run.side_effect = [
            "M\ttest/test_base_claude.py\nM\tsrc/resource/base_claude.py",
            "",   # diff for base_claude
        ]
        detector = ChangeDetector(repo_root=".")
        records = detector.detect(pr_number=1, pr_title="fix")
        file_paths = [r.file_path for r in records]
        self.assertNotIn("test/test_base_claude.py", file_paths)

    @patch("pipeline.second_brain.change_detector._run")
    def test_detect_no_changes_returns_empty(self, mock_run):
        """detect() returns an empty list when git reports no changes."""
        mock_run.return_value = ""
        detector = ChangeDetector(repo_root=".")
        records = detector.detect()
        self.assertEqual(records, [])

    @patch("pipeline.second_brain.change_detector._run")
    def test_detect_added_file(self, mock_run):
        """detect() marks a newly added file with ChangeType.added."""
        mock_run.side_effect = [
            "A\tpipeline/second_brain/new_module.py",
            "+class NewModule:\n+    pass",
        ]
        detector = ChangeDetector(repo_root=".")
        records = detector.detect()
        self.assertEqual(records[0].change_type, ChangeType.added)

    @patch("pipeline.second_brain.change_detector._run")
    def test_diff_stat_contains_plus_minus(self, mock_run):
        """detect() computes a diff_stat string with correct added/removed counts."""
        mock_run.side_effect = [
            "M\tsrc/resource/base_openai.py",
            "+added line\n+another add\n-removed line",
        ]
        detector = ChangeDetector(repo_root=".")
        records = detector.detect()
        self.assertIn("+2", records[0].diff_stat)
        self.assertIn("-1", records[0].diff_stat)


# ---------------------------------------------------------------------------
# _collect_py_files (kb_initialiser)
# ---------------------------------------------------------------------------

class TestCollectPyFiles(unittest.TestCase):
    """Tests for the _collect_py_files repository-scanning helper."""

    def test_collects_src_files(self):
        """Files under src/ and pipeline/ are collected with forward-slash paths."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "resource").mkdir(parents=True)
            (root / "src" / "resource" / "base_claude.py").write_text("x=1")
            (root / "src" / "resource" / "base_openai.py").write_text("x=1")
            (root / "pipeline" / "second_brain").mkdir(parents=True)
            (root / "pipeline" / "second_brain" / "vault_retriever.py").write_text("x=1")
            files = _collect_py_files(root)
        self.assertIn("src/resource/base_claude.py", files)
        self.assertIn("src/resource/base_openai.py", files)
        self.assertIn("pipeline/second_brain/vault_retriever.py", files)

    def test_excludes_test_files(self):
        """Files under a tests/ directory are excluded while other app files are kept."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "tests").mkdir(parents=True)
            (root / "src" / "tests" / "test_foo.py").write_text("x=1")
            (root / "src" / "app").mkdir(parents=True)
            (root / "src" / "app" / "agent.py").write_text("x=1")
            files = _collect_py_files(root)
        paths = [f.replace("\\", "/") for f in files]
        self.assertNotIn("src/tests/test_foo.py", paths)
        self.assertIn("src/app/agent.py", paths)

    def test_includes_orchestrator(self):
        """A top-level orchestrator.py file is included in the collected files."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "orchestrator.py").write_text("x=1")
            files = _collect_py_files(root)
        self.assertIn("orchestrator.py", files)

    def test_empty_repo_returns_empty(self):
        """An empty repository root yields an empty file list."""
        with TemporaryDirectory() as tmp:
            files = _collect_py_files(Path(tmp))
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
