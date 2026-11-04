"""Guard: the gateway package never imports the fake provider."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pytest

SWITCHYARD_DIR = Path(__file__).resolve().parents[3] / "src" / "switchyard"
FORBIDDEN_ROOT = "fake_provider"


class ImportScanner:
    """Collects absolute module names imported by a Python source file."""

    def imports(self, path: Path) -> list[str]:
        """Return sorted, de-duplicated absolute imports of ``path``."""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
        return sorted(names)


@pytest.mark.unit
class SwitchyardDoesNotImportFakeProviderTest(unittest.TestCase):
    """``fake_provider`` is test infrastructure only."""

    def test_no_switchyard_module_imports_fake_provider(self) -> None:
        scanner = ImportScanner()
        sources = sorted(SWITCHYARD_DIR.rglob("*.py"))
        self.assertTrue(sources, f"no sources found under {SWITCHYARD_DIR}")
        offenders = [
            f"{path.relative_to(SWITCHYARD_DIR)}: {name}"
            for path in sources
            for name in scanner.imports(path)
            if name == FORBIDDEN_ROOT or name.startswith(f"{FORBIDDEN_ROOT}.")
        ]
        self.assertEqual([], offenders)
