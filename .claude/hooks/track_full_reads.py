"""PostToolUse hook on Read: tracks full source file reads in metrics.md.

When Claude proceeds past the guard and actually reads a .py source file,
this hook fires and increments full_reads in metrics.md.

Combined with index_hits (tracked in guard_file_reads.py), this gives
a real token efficiency ratio: index_hits / (index_hits + full_reads).

A high ratio means agents are using the index efficiently.
A low ratio means the index is stale or agents are ignoring the guard.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from _hook_utils import (
    PROJECT_MEMORY_ALLOWLIST,
    cached_index_keys,
    increment_metric,
    normalize_path,
)

METRICS_PATH = Path(".claude/project_memory/metrics.md")
INDEX_PATH = Path(".claude/project_memory/code_index.md")


def load_index_keys() -> set[str]:
    """Return indexed file keys from code_index.md using the LRU-cached helper.

    Returns:
        set[str]: All indexed file-path keys, or an empty set if the index
        file does not exist.
    """
    if not INDEX_PATH.exists():
        return set()
    stat = INDEX_PATH.stat()
    keys = cached_index_keys(str(INDEX_PATH), stat.st_mtime_ns, stat.st_size)
    return set(keys)


def is_indexed_source(file_path_str: str) -> bool:
    """Return True when the source file path exists in code_index.md.

    Args:
        file_path_str (str): File path to check, in either absolute or
            relative form.

    Returns:
        bool: True if the path matches an indexed key (exact or suffix match).
    """
    norm = normalize_path(file_path_str)
    for key in load_index_keys():
        if norm == key or norm.endswith(key) or key.endswith(norm):
            return True
    return False


def main() -> None:
    """Read the PostToolUse hook payload from stdin and record a full-read metric.

    Ignores non-Read tool calls, project-memory/config files, non-Python
    files, test files, and files under ``.claude``. For remaining Python
    source files, increments ``full_reads`` (and ``indexed_reads_proceeded``
    if the file was already indexed) in metrics.md.
    """
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if payload.get("tool_name") != "Read":
        sys.exit(0)

    file_path_str: str = payload.get("tool_input", {}).get("file_path", "")
    if not file_path_str:
        sys.exit(0)

    file_path = Path(file_path_str)

    # Only count reads of source Python files (not project memory or tests)
    if file_path.name in PROJECT_MEMORY_ALLOWLIST:
        sys.exit(0)
    if file_path.suffix != ".py":
        sys.exit(0)
    norm = normalize_path(file_path_str)
    if file_path.name.startswith("test_") or "/tests/" in norm or "/test/" in norm:
        sys.exit(0)
    if ".claude" in str(file_path):
        sys.exit(0)

    increment_metric(METRICS_PATH, "full_reads")
    if is_indexed_source(file_path_str):
        increment_metric(METRICS_PATH, "indexed_reads_proceeded")


if __name__ == "__main__":
    main()
