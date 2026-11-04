"""PreToolUse hook: intercepts Read tool calls on Python source files.

If the file is already in code_index.md, this hook injects the indexed
summary directly into Claude's context via hookSpecificOutput.additionalContext
BEFORE the Read executes. Claude sees the summary and can decide it doesn't
need the full file — the primary token reduction mechanism.

Outputs JSON to stdout (Claude Code structured hook format).
Exit code 0 = allow the tool to proceed (we advise, not block).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from _hook_utils import (
    PROJECT_MEMORY_ALLOWLIST,
    increment_metric,
    normalize_path,
    parse_index,
)

INDEX_PATH = Path(".claude/project_memory/code_index.md")
METRICS_PATH = Path(".claude/project_memory/metrics.md")


def emit(additional_context: str) -> None:
    """Output structured JSON hook response with injected context.

    Args:
        additional_context (str): Text to inject into the model's context via
            ``hookSpecificOutput.additionalContext``.
    """
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": additional_context,
        }
    }
    print(json.dumps(payload))


def main() -> None:
    """Read the PreToolUse hook payload from stdin and advise on Read calls.

    Ignores non-Read tool calls, project-memory/config files, non-Python
    files, and test files. For remaining Python source files, emits an
    index-hit summary (with a metrics bump) when the file is already indexed,
    or a not-indexed notice otherwise. Always exits 0 to allow the Read to
    proceed regardless.
    """
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if payload.get("tool_name") != "Read":
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    file_path_str: str = tool_input.get("file_path", "")

    if not file_path_str:
        sys.exit(0)

    file_path = Path(file_path_str)

    # Allow project memory, config, and non-Python files through uninterrupted
    if file_path.name in PROJECT_MEMORY_ALLOWLIST:
        sys.exit(0)
    if file_path.suffix != ".py":
        sys.exit(0)
    # Test files always need full reads — expected by unit-test agent
    norm = normalize_path(file_path_str)
    if file_path.name.startswith("test_") or "/test/" in norm:
        sys.exit(0)

    index = parse_index(INDEX_PATH)

    # Try exact match, then suffix-based match (handles abs vs rel path differences)
    section: str | None = index.get(norm)
    if not section:
        for key in index:
            if norm.endswith(key) or key.endswith(norm):
                section = index[key]
                break

    if section:
        increment_metric(METRICS_PATH, "index_hits")
        emit(
            f"[TOKEN GUARD — INDEX HIT] `{norm}` is already indexed.\n"
            f"Use the summary below. Only proceed with the Read if you need "
            f"specific implementation logic not visible in the signature list.\n"
            f"\n{'─' * 60}\n"
            f"{section}\n"
            f"{'─' * 60}\n"
            f"Decision: if the summary answers your question → SKIP the Read. "
            f"If you need logic details, line numbers, or method bodies → proceed."
        )
    else:
        emit(
            f"[TOKEN GUARD — NOT INDEXED] `{norm}` has no index entry yet.\n"
            f"Proceed with the Read. After writing/editing this file, "
            f"the PostToolUse hook will auto-index it for future sessions."
        )


if __name__ == "__main__":
    main()
