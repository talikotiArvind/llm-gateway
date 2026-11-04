"""Unit tests for VaultRetriever, covering all 6 required cases per spec."""

import unittest
from pathlib import Path

from pipeline.second_brain.vault_retriever import VaultRetriever


class TestVaultRetrieverEmptyVault(unittest.TestCase):
    """query() must return empty string when vault has no notes."""

    def test_query_returns_empty_on_empty_vault(self, tmp_path: Path | None = None) -> None:
        """query() on a vault directory with no .md files returns an empty string."""
        # Use a real temporary directory with no .md files
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            retriever = VaultRetriever(vault_path=td, use_embeddings=False)
            result = retriever.query("architecture patterns")
        self.assertEqual(result, "")


class TestVaultRetrieverWithNotes(unittest.TestCase):
    """Functional tests against a real (temporary) vault on disk."""

    def _make_vault(self, tmp_dir: str) -> VaultRetriever:
        """Populate a temporary vault with sample notes and return a retriever.

        Args:
            tmp_dir: Path to the temporary directory to populate.

        Returns:
            VaultRetriever: A retriever configured against the populated vault.
        """
        notes_dir = Path(tmp_dir) / "03-Resources"
        notes_dir.mkdir(parents=True)
        (notes_dir / "architecture-note.md").write_text(
            "# Architecture Patterns\n\nUse layered architecture. Separate concerns.",
            encoding="utf-8",
        )
        (notes_dir / "testing-note.md").write_text(
            "# Test Strategy\n\nWrite unit tests. Mock all external services.",
            encoding="utf-8",
        )
        (notes_dir / "code-note.md").write_text(
            "# Code Snippets\n\nUse dataclasses. Use type annotations everywhere.",
            encoding="utf-8",
        )
        return VaultRetriever(vault_path=tmp_dir, use_embeddings=False)

    def test_query_returns_relevant_note(self) -> None:
        """query() returns a result containing the matching note's topic."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            retriever = self._make_vault(td)
            result = retriever.query("architecture layered patterns")
        self.assertIn("architecture", result.lower())

    def test_query_top_k_limit_respected(self) -> None:
        """query() with top_k=1 returns a single note without a join separator."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            retriever = self._make_vault(td)
            # top_k=1 means at most one note body returned (no separator between multiple)
            result = retriever.query("architecture code test", top_k=1)
        # Separator "---" only appears when multiple notes are joined; with k=1 it should not
        self.assertNotIn("\n\n---\n\n", result)
        self.assertGreater(len(result), 0)

    def test_write_note_creates_file_with_frontmatter(self) -> None:
        """write_note() creates a file containing YAML frontmatter and the body content."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            retriever = VaultRetriever(vault_path=td, use_embeddings=False)
            path = retriever.write_note(
                title="myproject-coder",
                content="Here is some generated code.",
                folder="03-Resources/code-snippets",
                metadata={
                    "agent": "coder",
                    "project": "myproject",
                    "date": "2026-04-26T10:00:00",
                    "tags": ["second-brain", "coder", "myproject"],
                    "status": "draft",
                },
            )
            self.assertTrue(Path(path).exists(), f"Expected file at {path}")
            contents = Path(path).read_text(encoding="utf-8")
        self.assertIn("---", contents)
        self.assertIn("agent: coder", contents)
        self.assertIn("project: myproject", contents)
        self.assertIn("Here is some generated code.", contents)

    def test_write_note_does_not_overwrite_existing(self) -> None:
        """write_note() called twice with the same title creates two distinct files."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            retriever = VaultRetriever(vault_path=td, use_embeddings=False)
            metadata = {
                "agent": "reviewer",
                "project": "proj1",
                "date": "2026-04-26T10:00:00",
                "tags": ["second-brain", "reviewer", "proj1"],
                "status": "draft",
            }
            path1 = retriever.write_note(
                title="proj1-reviewer", content="First write.", folder="03-Resources", metadata=metadata
            )
            path2 = retriever.write_note(
                title="proj1-reviewer", content="Second write.", folder="03-Resources", metadata=metadata
            )
            # Assertions must be inside the context manager — tmpdir is deleted on exit
            self.assertNotEqual(path1, path2, "Second write should produce a new file, not overwrite")
            self.assertTrue(Path(path1).exists())
            self.assertTrue(Path(path2).exists())

    def test_retriever_disabled_when_vault_path_missing(self) -> None:
        """query() against a nonexistent vault path returns an empty string."""
        nonexistent = "/tmp/nonexistent_vault_xyzzy_12345"
        retriever = VaultRetriever(vault_path=nonexistent, use_embeddings=False)
        result = retriever.query("any topic")
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
