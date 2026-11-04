"""Unit tests for Step 1: kb_models, ast_summariser, kb_writer, kb_reader."""

from __future__ import annotations

import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from pipeline.second_brain.ast_summariser import ASTSummariser, _slug, _infer_layer
from pipeline.second_brain.kb_models import (
    ChangeType,
    ClassInfo,
    KBNote,
    LayerType,
    ModuleSnapshot,
    PRChangelog,
)
from pipeline.second_brain.kb_reader import KBReader
from pipeline.second_brain.kb_writer import KBWriter, _parse_frontmatter


# ---------------------------------------------------------------------------
# ModuleSnapshot / KBNote models
# ---------------------------------------------------------------------------

class TestKBModels(unittest.TestCase):
    """Tests for the ModuleSnapshot, KBNote, and PRChangelog data models."""

    def _snapshot(self) -> ModuleSnapshot:
        """Build a sample ModuleSnapshot for use across tests.

        Returns:
            ModuleSnapshot: A snapshot representing a single-class data-access module.
        """
        return ModuleSnapshot(
            file_path="src/resource/base_claude.py",
            module_slug="src--resource--base_claude",
            layer=LayerType.data_access,
            classes=[ClassInfo(name="ClaudeBaseAgent", docstring="Wraps Anthropic SDK.", methods=["run(task)"])],
            module_docstring="Claude base agent module.",
            top_level_functions=[],
            line_count=120,
        )

    def test_snapshot_fields(self):
        """ModuleSnapshot stores layer, classes, and line_count as given."""
        snap = self._snapshot()
        self.assertEqual(snap.layer, LayerType.data_access)
        self.assertEqual(snap.classes[0].name, "ClaudeBaseAgent")
        self.assertEqual(snap.line_count, 120)

    def test_kbnote_to_markdown_contains_module(self):
        """KBNote.to_markdown() renders module path, PR number, and prose summary."""
        note = KBNote(
            module="src/resource/base_claude.py",
            module_slug="src--resource--base_claude",
            layer="data-access",
            last_pr=7,
            last_updated=datetime(2026, 6, 27, tzinfo=timezone.utc),
            classes=["ClaudeBaseAgent"],
            key_methods=["run", "_get_vault_context"],
            change_type=ChangeType.modified,
            prose_summary="ClaudeBaseAgent wraps the Anthropic SDK.",
            model_used="claude-haiku-4-5-20251001",
            pr_title="feat: add vault write-back",
        )
        md = note.to_markdown()
        self.assertIn("src/resource/base_claude.py", md)
        self.assertIn("PR #7", md)
        self.assertIn("ClaudeBaseAgent wraps the Anthropic SDK.", md)
        self.assertIn("last_pr: 7", md)

    def test_pr_changelog_to_markdown(self):
        """PRChangelog.to_markdown() renders the PR number and file summary."""
        cl = PRChangelog(
            pr_number=12,
            pr_title="feat: A2A streaming",
            merged_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
            files_changed=["src/resource/base_claude.py"],
            summaries={"src/resource/base_claude.py": "Added streaming support."},
        )
        md = cl.to_markdown()
        self.assertIn("PR #12", md)
        self.assertIn("Added streaming support.", md)


# ---------------------------------------------------------------------------
# ASTSummariser
# ---------------------------------------------------------------------------

class TestASTSummariser(unittest.TestCase):
    """Tests for ASTSummariser and its module-level helpers."""

    def _write_py(self, tmp: str, name: str, src: str) -> str:
        """Write a dedented Python source snippet to a temp file.

        Args:
            tmp: Directory to write the file into.
            name: File name to create.
            src: Source text (will be dedented) to write.

        Returns:
            str: Path to the written file.
        """
        p = Path(tmp) / name
        p.write_text(textwrap.dedent(src), encoding="utf-8")
        return str(p)

    def test_summarise_class_and_methods(self):
        """summarise() extracts module docstring, class name, and public methods."""
        with TemporaryDirectory() as tmp:
            path = self._write_py(tmp, "agent.py", """
                \"\"\"My module.\"\"\"
                class MyAgent:
                    \"\"\"Does stuff.\"\"\"
                    def run(self, task: str) -> str: ...
                    def _private(self): ...
                    def status(self) -> str: ...
            """)
            snap = ASTSummariser().summarise(path)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.module_docstring, "My module.")
        self.assertEqual(len(snap.classes), 1)
        self.assertEqual(snap.classes[0].name, "MyAgent")
        self.assertIn("run(task)", snap.classes[0].methods)
        self.assertIn("status()", snap.classes[0].methods)
        self.assertNotIn("_private()", snap.classes[0].methods)

    def test_summarise_top_level_functions(self):
        """summarise() collects public top-level functions and excludes private ones."""
        with TemporaryDirectory() as tmp:
            path = self._write_py(tmp, "helpers.py", """
                def build_agent(name): ...
                def _internal(): ...
            """)
            snap = ASTSummariser().summarise(path)
        self.assertIn("build_agent(name)", snap.top_level_functions)
        self.assertNotIn("_internal()", snap.top_level_functions)

    def test_summarise_missing_file_returns_none(self):
        """summarise() on a nonexistent file path returns None."""
        snap = ASTSummariser().summarise("no/such/file.py")
        self.assertIsNone(snap)

    def test_summarise_many_filters_none(self):
        """summarise_many() drops entries for files that fail to summarise."""
        with TemporaryDirectory() as tmp:
            good = self._write_py(tmp, "ok.py", "x = 1")
            snaps = ASTSummariser().summarise_many([good, "missing.py"])
        self.assertEqual(len(snaps), 1)

    def test_slug(self):
        """_slug() converts a file path into a double-dash-separated slug."""
        self.assertEqual(_slug("src/resource/base_claude.py"), "src--resource--base_claude")

    def test_infer_layer_data_access(self):
        """_infer_layer() classifies src/resource paths as data_access."""
        self.assertEqual(_infer_layer("src/resource/base_claude.py"), LayerType.data_access)

    def test_infer_layer_api(self):
        """_infer_layer() classifies rag_pipeline/api paths as api."""
        self.assertEqual(_infer_layer("rag_pipeline/api/main.py"), LayerType.api)

    def test_infer_layer_pipeline(self):
        """_infer_layer() classifies pipeline/second_brain paths as pipeline."""
        self.assertEqual(_infer_layer("pipeline/second_brain/vault_retriever.py"), LayerType.pipeline)

    def test_infer_layer_unknown(self):
        """_infer_layer() classifies unrecognized paths as unknown."""
        self.assertEqual(_infer_layer("utils/misc.py"), LayerType.unknown)

    def test_line_count(self):
        """summarise() reports the exact line count of the source file."""
        with TemporaryDirectory() as tmp:
            path = self._write_py(tmp, "lines.py", "x = 1\ny = 2\nz = 3")
            snap = ASTSummariser().summarise(path)
        self.assertEqual(snap.line_count, 3)


# ---------------------------------------------------------------------------
# KBWriter + KBReader
# ---------------------------------------------------------------------------

class TestKBWriterReader(unittest.TestCase):
    """Tests for KBWriter and KBReader against a temporary vault directory."""

    def _note(self) -> KBNote:
        """Build a sample KBNote for use across tests.

        Returns:
            KBNote: A note describing the OpenAI base agent module.
        """
        return KBNote(
            module="src/resource/base_openai.py",
            module_slug="src--resource--base_openai",
            layer="data-access",
            last_pr=5,
            last_updated=datetime(2026, 6, 27, tzinfo=timezone.utc),
            classes=["OpenAIBaseAgent"],
            key_methods=["run"],
            change_type=ChangeType.added,
            prose_summary="Wraps the OpenAI Agents SDK.",
            model_used="claude-haiku-4-5-20251001",
            pr_title="feat: add openai base",
        )

    def test_write_module_note_creates_file(self):
        """write_module_note() creates a file whose content includes the module path."""
        with TemporaryDirectory() as vault:
            writer = KBWriter(vault)
            path = writer.write_module_note(self._note())
            self.assertTrue(Path(path).exists())
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("src/resource/base_openai.py", content)

    def test_write_module_note_upserts(self):
        """write_module_note() on the same module updates the existing file in place."""
        with TemporaryDirectory() as vault:
            writer = KBWriter(vault)
            note = self._note()
            writer.write_module_note(note)
            note2 = note.model_copy(update={"prose_summary": "Updated summary."})
            writer.write_module_note(note2)
            files = list((Path(vault) / "kb" / "modules").glob("*.md"))
            self.assertEqual(len(files), 1)
            self.assertIn("Updated summary.", files[0].read_text(encoding="utf-8"))

    def test_write_changelog(self):
        """write_changelog() creates a file named with the zero-padded PR number."""
        with TemporaryDirectory() as vault:
            cl = PRChangelog(
                pr_number=3,
                pr_title="fix: gemini loop",
                merged_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
                files_changed=["src/resource/base_gemini.py"],
                summaries={"src/resource/base_gemini.py": "Fixed loop exit condition."},
            )
            path = KBWriter(vault).write_changelog(cl)
            self.assertTrue(Path(path).exists())
            self.assertIn("pr-0003", path)

    def test_write_index(self):
        """write_index() produces an index file listing the KB title and known modules."""
        with TemporaryDirectory() as vault:
            writer = KBWriter(vault)
            writer.write_module_note(self._note())
            index_path = writer.write_index()
            content = Path(index_path).read_text(encoding="utf-8")
            self.assertIn("Knowledge Base Index", content)
            self.assertIn("src/resource/base_openai.py", content)

    def test_reader_get_context(self):
        """get_context() returns text containing the written note's prose summary."""
        with TemporaryDirectory() as vault:
            KBWriter(vault).write_module_note(self._note())
            reader = KBReader(vault)
            ctx = reader.get_context("src/resource/base_openai.py")
            self.assertIn("Wraps the OpenAI Agents SDK.", ctx)

    def test_reader_missing_returns_empty(self):
        """get_context() for a module with no note returns an empty string."""
        with TemporaryDirectory() as vault:
            reader = KBReader(vault)
            self.assertEqual(reader.get_context("no/such/module.py"), "")

    def test_reader_has_note(self):
        """has_note() reports True for a written module and False for an unwritten one."""
        with TemporaryDirectory() as vault:
            KBWriter(vault).write_module_note(self._note())
            reader = KBReader(vault)
            self.assertTrue(reader.has_note("src/resource/base_openai.py"))
            self.assertFalse(reader.has_note("src/resource/base_gemini.py"))

    def test_reader_list_modules(self):
        """list_modules() includes the slug of a module with a written note."""
        with TemporaryDirectory() as vault:
            KBWriter(vault).write_module_note(self._note())
            modules = KBReader(vault).list_modules()
            self.assertIn("src--resource--base_openai", modules)


class TestParseFrontmatter(unittest.TestCase):
    """Tests for the _parse_frontmatter helper."""

    def test_parses_simple_keys(self):
        """_parse_frontmatter() extracts key-value pairs from a YAML frontmatter block."""
        text = "---\nmodule: src/foo.py\nlayer: data-access\nlast_pr: 5\n---\n\nbody"
        result = _parse_frontmatter(text)
        self.assertEqual(result["module"], "src/foo.py")
        self.assertEqual(result["layer"], "data-access")

    def test_no_frontmatter_returns_empty(self):
        """_parse_frontmatter() on text without a frontmatter block returns an empty dict."""
        self.assertEqual(_parse_frontmatter("just content"), {})


if __name__ == "__main__":
    unittest.main()
