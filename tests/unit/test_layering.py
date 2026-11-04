"""Layering guards: the domain stays pure and every application module is layered (FR-13)."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import tomllib
import unittest
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_DIR = REPO_ROOT / "src" / "switchyard" / "domain"
APPLICATION_DIR = REPO_ROOT / "src" / "switchyard" / "application"
PYPROJECT = REPO_ROOT / "pyproject.toml"
APPLICATION_MODULE_RE = re.compile(r"switchyard\.application\.[A-Za-z_][A-Za-z0-9_]*")
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


class LayersContract:
    """Reads the import-linter ``layers`` contract and finds application modules it misses."""

    def __init__(self, layers: Iterable[str]) -> None:
        self._named = frozenset(
            name for layer in layers for name in APPLICATION_MODULE_RE.findall(layer)
        )

    @classmethod
    def from_pyproject(cls, path: Path) -> LayersContract:
        """Load the contract whose id is ``layers`` from ``path``."""
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        contracts = config["tool"]["importlinter"]["contracts"]
        layers = next(c["layers"] for c in contracts if c.get("id") == "layers")
        return cls(layers)

    @staticmethod
    def application_modules(package_dir: Path) -> list[str]:
        """Return the sorted top-level modules and subpackages of ``package_dir``."""
        names = {p.stem for p in package_dir.glob("*.py") if p.name != "__init__.py"}
        names |= {p.parent.name for p in package_dir.glob("*/__init__.py")}
        return sorted(f"switchyard.application.{name}" for name in names)

    def unlayered(self, modules: Iterable[str]) -> list[str]:
        """Return the sorted modules that no layer names."""
        return sorted(m for m in modules if m not in self._named)


@pytest.mark.unit
class ApplicationLayeringTest(unittest.TestCase):
    """A new switchyard.application module cannot escape the layers contract."""

    def setUp(self) -> None:
        self.contract = LayersContract.from_pyproject(PYPROJECT)

    def test_every_application_module_is_layered(self) -> None:
        modules = LayersContract.application_modules(APPLICATION_DIR)
        self.assertEqual([], self.contract.unlayered(modules))

    def test_unlisted_module_is_reported(self) -> None:
        contract = LayersContract(["(switchyard.application.budget_service) | switchyard.security"])
        found = contract.unlayered(
            ["switchyard.application.dto", "switchyard.application.budget_service"]
        )
        self.assertEqual(["switchyard.application.dto"], found)

    def test_module_discovery_includes_subpackages(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "ports.py").write_text("", encoding="utf-8")
            (root / "dto").mkdir()
            (root / "dto" / "__init__.py").write_text("", encoding="utf-8")
            found = LayersContract.application_modules(root)
        self.assertEqual(["switchyard.application.dto", "switchyard.application.ports"], found)


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
            # lint-imports prints Unicode; never decode with the locale codec (cp1252 on Windows).
            encoding="utf-8",
            errors="replace",
            timeout=LINT_IMPORTS_TIMEOUT_S,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
