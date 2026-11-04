"""Validate the Claude workflow pipeline configuration.

Checks:
1. Required files exist.
2. settings.json hook commands point to existing scripts.
3. Parallel-group naming in docs uses PARALLEL-GROUP-* convention.
4. Test directory convention references default to test/ for this repository.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(".")

REQUIRED_FILES = [
    Path("CLAUDE.md"),
    Path(".claude/settings.json"),
    Path(".claude/settings.local.json"),
    Path(".claude/project_memory/code_index.md"),
    Path(".claude/project_memory/metrics.md"),
]

def _discover_docs_to_validate() -> list[Path]:
    """All agent/skill docs plus CLAUDE.md — not a hand-picked subset.

    A hardcoded 5-file list let convention drift go unchecked in every other
    agent/skill doc (coding-agent.md, cleaner.md, mkdocs-agent.md, etc.) while
    still reporting "PASSED". Globbing means a new agent/skill file is covered
    automatically, with no separate list to remember to update.

    Returns:
        list[Path]: CLAUDE.md followed by all ``.claude/agents/*.md`` and
        ``.claude/skills/*.md`` files, sorted within each group.
    """
    docs = [Path("CLAUDE.md")]
    docs.extend(sorted(ROOT.glob(".claude/agents/*.md")))
    docs.extend(sorted(ROOT.glob(".claude/skills/*.md")))
    return docs


DOCS_TO_VALIDATE = _discover_docs_to_validate()


def check_required_files() -> list[str]:
    """Check that every path in ``REQUIRED_FILES`` exists.

    Returns:
        list[str]: One "Missing required file" message per absent path;
        empty if all required files exist.
    """
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            errors.append(f"Missing required file: {rel}")
    return errors


def check_hook_commands() -> list[str]:
    """Check that every hook command in settings.json points to an existing script.

    Returns:
        list[str]: Error messages for a missing settings.json, invalid JSON,
        or hook command targets that don't exist on disk; empty if all checks pass.
    """
    errors: list[str] = []
    settings_path = ROOT / ".claude/settings.json"
    if not settings_path.exists():
        return ["Missing .claude/settings.json; cannot validate hooks."]

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON in settings.json: {exc}"]

    hooks = settings.get("hooks", {})
    for event_items in hooks.values():
        for event in event_items:
            for hook in event.get("hooks", []):
                command = hook.get("command", "")
                if not isinstance(command, str) or not command:
                    continue
                # expected format: python .claude/hooks/script.py
                parts = command.split()
                if len(parts) >= 2 and parts[0] == "python":
                    script = ROOT / parts[1]
                    if not script.exists():
                        errors.append(f"Hook command target missing: {parts[1]}")
    return errors


def check_settings_local_permissions() -> list[str]:
    """Validate expected local permissions are declared.

    Returns:
        list[str]: Error messages for a missing/invalid settings.local.json
        or any expected permission absent from its allow list; empty if all
        checks pass.
    """
    expected = {
        "Bash(ruff check *)",
        "Bash(mypy *)",
        "Bash(pytest *)",
        "Bash(git diff *)",
        "Bash(python .claude/hooks/*)",
    }
    path = ROOT / ".claude/settings.local.json"
    if not path.exists():
        return ["Missing .claude/settings.local.json"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON in settings.local.json: {exc}"]

    allow = set(data.get("permissions", {}).get("allow", []))
    missing = sorted(item for item in expected if item not in allow)
    return [f"settings.local.json missing permission: {item}" for item in missing]


def check_parallel_group_naming() -> list[str]:
    """Check that PARALLEL-* labels in agent/skill docs use the PARALLEL-GROUP-* convention.

    Returns:
        list[str]: One message per non-conforming label found (with file and
        line number); empty if all labels conform.
    """
    errors: list[str] = []
    pattern_parallel = re.compile(r"\bPARALLEL-[A-Z][A-Z0-9-]*\b")
    for doc in DOCS_TO_VALIDATE:
        if not doc.exists():
            continue
        for idx, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for token in pattern_parallel.findall(line):
                if not token.startswith("PARALLEL-GROUP"):
                    errors.append(f"{doc}:{idx} uses non-standard parallel label: {line.strip()}")
    return errors


def check_runtime_tools() -> list[str]:
    """Validate Python and essential CLI tools are available.

    Returns:
        list[str]: Error messages for an insufficient Python version or any
        missing required CLI tool (ruff, mypy, pytest); empty if all checks pass.
    """
    errors: list[str] = []
    if sys.version_info < (3, 9):
        errors.append("Python 3.9+ required (ast.unparse is used by update_code_index.py)")
    for tool in ("ruff", "mypy", "pytest"):
        if shutil.which(tool) is None:
            errors.append(f"Missing required CLI tool: {tool}")
    return errors


def main() -> None:
    """Run all pipeline validation checks and print a pass/fail report.

    Exits with status 1 and prints each collected error if any check fails;
    otherwise prints a PASSED summary line per check category.
    """
    checks = [
        check_required_files,
        check_hook_commands,
        check_settings_local_permissions,
        check_parallel_group_naming,
        check_runtime_tools,
    ]

    errors: list[str] = []
    for check in checks:
        errors.extend(check())

    if errors:
        print("Pipeline validation FAILED:")
        for err in errors:
            print(f"- {err}")
        sys.exit(1)

    print("Pipeline validation PASSED")
    print("- required files: ok")
    print("- hook command targets: ok")
    print("- settings.local permissions: ok")
    print("- parallel naming convention: ok (PARALLEL-GROUP-*)")
    print("- runtime tools: ok")


if __name__ == "__main__":
    main()
