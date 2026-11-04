"""Layering guard: the domain package stays pure (FR-13)."""

from __future__ import annotations

import ast
import shutil
import subprocess
import unittest
from pathlib import Path

import pytest

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "src" / "switchyard" / "domain"
DOMAIN_IMPORT_ALLOWLIST = frozenset(
    {
        "__future__",
        "abc",
        "collections",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "functools",
        "hashlib",
        "itertools",
        "json",
        "math",
        "random",
        "re",
        "typing",
        "uuid",
        "pydantic",
        "switchyard.domain",
    }
)
LINT_IMPORTS_TIMEOUT_S = 120


class DomainImportCollector:
    """Extracts absolute imported module names from Python source."""

    def collect(self, source: str, filename: str) -> list[str]:
        """Return the sorted, de-duplicated absolute module names imported by ``source``."""
        tree = ast.parse(source, filename=filename)
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
        return sorted(names)

    @staticmethod
    def is_allowed(module: str) -> bool:
        """Return True when ``module`` or one of its parent packages is allowlisted."""
        parts = module.split(".")
        prefixes = (".".join(parts[:i]) for i in range(1, len(parts) + 1))
        return any(prefix in DOMAIN_IMPORT_ALLOWLIST for prefix in prefixes)


@pytest.mark.unit
class DomainLayeringTest(unittest.TestCase):
    """The domain layer imports only the stdlib allowlist, pydantic and itself."""

    def setUp(self) -> None:
        self.collector = DomainImportCollector()

    def test_domain_package_exists(self) -> None:
        self.assertTrue((DOMAIN_DIR / "__init__.py").is_file())

    def test_domain_imports_are_allowlisted(self) -> None:
        violations: list[str] = []
        for path in sorted(DOMAIN_DIR.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for module in self.collector.collect(source, str(path)):
                if not self.collector.is_allowed(module):
                    violations.append(f"{path.name}: {module}")
        self.assertEqual([], violations)

    def test_collector_flags_forbidden_import(self) -> None:
        source = "import os\nfrom httpx import AsyncClient\nfrom .schema import X\n"
        modules = self.collector.collect(source, "<sample>")
        self.assertEqual(["httpx", "os"], modules)
        self.assertFalse(any(self.collector.is_allowed(m) for m in modules))

    def test_allowlist_accepts_submodules(self) -> None:
        self.assertTrue(self.collector.is_allowed("collections.abc"))
        self.assertTrue(self.collector.is_allowed("switchyard.domain.schema"))
        self.assertFalse(self.collector.is_allowed("switchyard.infrastructure"))

    def test_import_linter_contracts_kept(self) -> None:
        executable = shutil.which("lint-imports")
        if executable is None:
            self.skipTest("lint-imports is not installed in this environment")
        result = subprocess.run(  # fixed, trusted executable; no shell
            [executable],
            capture_output=True,
            text=True,
            timeout=LINT_IMPORTS_TIMEOUT_S,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
